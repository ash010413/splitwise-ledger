"""Transactional, paged Firestore ledger for the small-group Cloud Run deployment.

Expenses are distributed over 64 bounded documents, rather than one growing document
or thousands of billable reads on every refresh. A versioned metadata document is
read in every transaction; a bounded immutable cache avoids re-reading unchanged
pages. Financial decisions and their audit events commit atomically. No local file
is authoritative, and two Cloud Run revisions cannot silently overwrite each other.
"""

import copy
import hashlib
import json
import threading
import time
import uuid
from collections import OrderedDict
from contextvars import ContextVar

from fastapi import HTTPException
from google.cloud import firestore

from .domain import Category, classify, normalize_description
from .store import ConflictError

CURRENT_OPERATION = ContextVar("minto_cloud_operation", default=None)
PAGE_COUNT = 64
_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()


def pack(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def clean(row):
    return dict(row["payload"], category=row["category"], reason=row["reason"])


def event(events, expense_id, action, payload):
    events.append(
        {"expense_id": expense_id, "action": action, "payload": payload, "created_at": time.time()}
    )


def rematch(rows, rules, events):
    changed = 0
    for row in rows.values():
        record = row["payload"]
        if not record["excluded"] and row["reason"] in {"human", "source_changed"}:
            continue
        category, reason = classify(record, rules)
        if (
            row["reason"] in {"gemini", "historical_fallback"}
            and not record["excluded"]
            and category is None
            and reason != "conflicting_rules"
        ):
            continue
        if category == row["category"] and reason == row["reason"]:
            continue
        row.update(category=category, reason=reason)
        event(events, record["id"], "category_matched", {"category": category, "reason": reason})
        changed += 1
    return changed


class FirestoreLedger:
    def __init__(self, client, user_id):
        self.client, self.user_id = client, int(user_id)
        self.ref = client.collection("minto_ledgers").document(str(self.user_id))

    def _run(self, change):
        committed = {}

        @firestore.transactional
        def execute(tx):
            snapshot = self.ref.get(transaction=tx)
            original = snapshot.to_dict() or {
                "settings": {},
                "rules": [],
                "pages": {},
                "version": "empty",
            }
            cache_key = (self.client.project, self.user_id, original["version"])
            with _CACHE_LOCK:
                cached = _CACHE.get(cache_key)
            if cached is None:
                rows = {}
                refs = [self.ref.collection("pages").document(page) for page in original["pages"]]
                for page in self.client.get_all(refs, transaction=tx) if refs else []:
                    if not page.exists:
                        raise ValueError("Incomplete ledger pages")
                    content = page.to_dict()["content"]
                    if hashlib.sha256(content.encode()).hexdigest() != original["pages"][page.id]:
                        raise ValueError("Ledger page checksum mismatch")
                    rows.update(json.loads(content))
            else:
                rows = cached
            rows = copy.deepcopy(rows)
            meta = copy.deepcopy(original)
            events = []
            result = change(meta, rows, events)
            pages = {}
            for key, row in rows.items():
                page = str(int(key) % PAGE_COUNT)
                pages.setdefault(page, {})[key] = row
            encoded = {page: pack(entries) for page, entries in pages.items()}
            if any(len(content.encode()) > 850_000 for content in encoded.values()):
                raise ValueError("Ledger page capacity exceeded; import retained for retry")
            hashes = {
                page: hashlib.sha256(content.encode()).hexdigest()
                for page, content in encoded.items()
            }
            meta["pages"] = hashes
            changed = meta != original or bool(events)
            if changed:
                # A worker whose operation lease expired must never commit stale source data.
                operation = CURRENT_OPERATION.get()
                if operation and operation[0] == self.user_id:
                    lease = (
                        self.client.collection("minto_leases")
                        .document(str(self.user_id))
                        .get(transaction=tx)
                        .to_dict()
                        or {}
                    )
                    if lease.get("owner") != operation[1] or lease.get("expires", 0) <= time.time():
                        raise HTTPException(409, "Sync lease expired; please retry")
                meta["version"] = uuid.uuid4().hex
                writes = [
                    (page, content)
                    for page, content in encoded.items()
                    if original["pages"].get(page) != hashes[page]
                ]
                audits = [pack(events[i : i + 100]) for i in range(0, len(events), 100)]
                if (
                    sum(len(content.encode()) for _, content in writes)
                    + sum(len(a.encode()) for a in audits)
                    > 8_000_000
                ):
                    raise ValueError(
                        "Import exceeds atomic commit capacity; previous spending retained"
                    )
                for page, content in writes:
                    tx.set(self.ref.collection("pages").document(page), {"content": content})
                for page in original["pages"].keys() - hashes.keys():
                    tx.delete(self.ref.collection("pages").document(page))
                for audit in audits:
                    tx.set(
                        self.ref.collection("audit").document(uuid.uuid4().hex), {"content": audit}
                    )
                tx.set(self.ref, meta)
            committed.update(version=meta["version"], rows=rows)
            return result

        result = execute(self.client.transaction())
        with _CACHE_LOCK:
            _CACHE[(self.client.project, self.user_id, committed["version"])] = copy.deepcopy(
                committed["rows"]
            )
            while len(_CACHE) > 6:
                _CACHE.popitem(last=False)
        return result

    def get(self, key):
        return (self.ref.get().to_dict() or {}).get("settings", {}).get(key)

    def set_many(self, values):
        def update(meta, rows, events):
            meta["settings"].update(values)

        self._run(update)

    def save_batch(self, records, cursor, synced_at=None):
        def update(meta, rows, events):
            settings = meta["settings"]
            # Freeze existing imports before adding IDs from a new incremental fetch.
            if "history_initialized" not in settings and "sync_cursor" in settings:
                for row in rows.values():
                    row["historical"] = True
                settings["history_initialized"] = True
            for record in records:
                key = str(record["id"])
                old = rows.get(key)
                if old and old["revision"] == record["revision"]:
                    continue
                category, reason = classify(record, meta["rules"])
                if old and old["reason"] == "human" and not record["excluded"]:
                    category, reason = None, "source_changed"
                rows[key] = {
                    "payload": record,
                    "revision": record["revision"],
                    "category": category,
                    "reason": reason,
                    "historical": old.get("historical", False) if old else False,
                    "ai": old.get("ai", {}) if old else {},
                }
                event(
                    events,
                    record["id"],
                    "source_updated" if old else "imported",
                    {"revision": record["revision"], "category": category, "reason": reason},
                )
            rematch(rows, meta["rules"], events)
            if "history_initialized" not in settings:
                for row in rows.values():
                    row["historical"] = True
                settings["history_initialized"] = True
            settings["sync_cursor"] = cursor
            if synced_at is not None:
                settings["last_successful_sync_at"] = synced_at

        self._run(update)

    def expenses(self):
        return self._run(
            lambda meta, rows, events: [
                clean(row)
                for _, row in sorted(rows.items(), key=lambda item: int(item[0]), reverse=True)
            ]
        )

    def reclassify(self, policy=None):
        def update(meta, rows, events):
            changed = rematch(rows, meta["rules"], events)
            if policy:
                for key, row in rows.items():
                    decision = row.get("ai", {}).get(policy)
                    if row["reason"] == "historical_fallback" and (
                        not decision or decision["revision"] != row["revision"]
                    ):
                        row.update(category=None, reason="needs_review")
                        event(events, int(key), "category_policy_retry", {"policy": policy})
                        changed += 1
            return changed

        return self._run(update)

    def begin_history(self):
        def update(meta, rows, events):
            if "history_initialized" in meta["settings"] or "sync_cursor" not in meta["settings"]:
                return
            for row in rows.values():
                row["historical"] = True
            meta["settings"]["history_initialized"] = True

        self._run(update)

    def historical_ids(self):
        return self._run(
            lambda meta, rows, events: {
                int(key) for key, row in rows.items() if row.get("historical")
            }
        )

    def finish_history(self, policy):
        def update(meta, rows, events):
            changed = 0
            for key, row in rows.items():
                decision = row.get("ai", {}).get(policy)
                if (
                    not row.get("historical")
                    or row["category"] is not None
                    or row["reason"] in {"human", "source_changed", "conflicting_rules"}
                ):
                    continue
                if (
                    not decision
                    or decision["revision"] != row["revision"]
                    or decision["category"] is not None
                ):
                    continue
                row.update(category=Category.OTHERS.value, reason="historical_fallback")
                event(
                    events,
                    int(key),
                    "historical_fallback",
                    {"category": Category.OTHERS.value, "policy": policy},
                )
                changed += 1
            return changed

        return self._run(update)

    def ai_pending(self, policy, limit=None):
        def collect(meta, rows, events):
            groups = {}
            for _, row in sorted(rows.items(), key=lambda item: int(item[0]), reverse=True):
                record = row["payload"]
                decision = row.get("ai", {}).get(policy)
                if (
                    record["excluded"]
                    or row["category"] is not None
                    or row["reason"] in {"human", "source_changed", "conflicting_rules"}
                    or (decision and decision["revision"] == row["revision"])
                ):
                    continue
                key = (
                    normalize_description(record["description"]),
                    record["group_id"],
                    record["currency"],
                    (record.get("source_category") or {}).get("name", ""),
                )
                if key not in groups and limit is not None and len(groups) >= limit:
                    continue
                groups.setdefault(key, []).append(clean(row))
            return list(groups.values())

        return self._run(collect)

    def apply_ai_decisions(self, groups, decisions, policy, model):
        def update(meta, rows, events):
            matched = review = 0
            for decision in decisions:
                category = (
                    decision.category.value if decision.certain and decision.category else None
                )
                for original in groups[decision.item]:
                    row = rows.get(str(original["id"]))
                    if (
                        not row
                        or row["revision"] != original["revision"]
                        or row["category"]
                        or row["reason"] in {"human", "source_changed", "conflicting_rules"}
                        or row["payload"]["excluded"]
                    ):
                        continue
                    row.setdefault("ai", {})[policy] = {
                        "revision": row["revision"],
                        "category": category,
                        "reason": decision.reason,
                        "model": model,
                    }
                    if category:
                        row.update(category=category, reason="gemini")
                        matched += 1
                    else:
                        review += 1
                    event(
                        events,
                        original["id"],
                        "gemini_category",
                        {
                            "revision": row["revision"],
                            "category": category,
                            "reason": decision.reason,
                            "policy": policy,
                            "model": model,
                        },
                    )
            return matched, review

        return self._run(update)

    def review(self, expense_id, revision, category, remember):
        def update(meta, rows, events):
            row = rows.get(str(expense_id))
            if not row:
                raise KeyError(expense_id)
            if row["revision"] != revision:
                raise ConflictError("Expense changed; reload before categorizing")
            if row["payload"]["excluded"]:
                raise ConflictError("Settled, deleted or zero-share expenses cannot be categorized")
            previous = row["category"]
            row.update(category=category.value, reason="human")
            if remember:
                description = normalize_description(row["payload"]["description"])
                if not description:
                    raise ConflictError("Cannot remember an empty description")
                meta["rules"].append(
                    {
                        "description": description,
                        "group_id": row["payload"]["group_id"],
                        "currency": row["payload"]["currency"],
                        "category": category.value,
                    }
                )
                rematch(rows, meta["rules"], events)
            event(
                events,
                expense_id,
                "human_review",
                {
                    "previous_category": previous,
                    "category": category.value,
                    "revision": revision,
                    "remember": remember,
                },
            )

        self._run(update)
