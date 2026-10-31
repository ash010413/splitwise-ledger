"""SQLite unit of work. Single-account, single-worker prototype."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .domain import Category, classify, normalize_description


class ConflictError(Exception):
    pass


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY, revision TEXT NOT NULL, payload TEXT NOT NULL,
                    category TEXT, reason TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rules (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS historical_expenses (id INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, expense_id INTEGER NOT NULL,
                    action TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_decisions (
                    expense_id INTEGER NOT NULL, revision TEXT NOT NULL, policy TEXT NOT NULL,
                    category TEXT, reason TEXT NOT NULL, model TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(expense_id,revision,policy)
                );
            """)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, key: str):
        with self.transaction() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def set_many(self, values):
        with self.transaction() as db:
            for key, value in values.items():
                self.put(db, key, value)

    @staticmethod
    def put(db, key, value):
        db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))

    @staticmethod
    def audit(db, expense_id, action, payload):
        db.execute(
            "INSERT INTO audit(expense_id,action,payload,created_at) VALUES (?,?,?,?)",
            (expense_id, action, json.dumps(payload), datetime.now(UTC).isoformat()),
        )

    def save_batch(self, records: list[dict], cursor: str, synced_at: float | None = None):
        # Cursor advances only with a successfully persisted complete fetch.
        with self.transaction() as db:
            rules = [json.loads(r[0]) for r in db.execute("SELECT payload FROM rules")]
            for record in records:
                old = db.execute("SELECT * FROM expenses WHERE id=?", (record["id"],)).fetchone()
                if old and old["revision"] == record["revision"]:
                    continue
                category, reason = classify(record, rules)
                # A material edit invalidates human approval even if a remembered rule matches.
                if old and old["reason"] == "human" and not record["excluded"]:
                    category, reason = None, "source_changed"
                db.execute(
                    "INSERT OR REPLACE INTO expenses VALUES (?,?,?,?,?)",
                    (
                        record["id"],
                        record["revision"],
                        json.dumps(record),
                        category,
                        reason,
                    ),
                )
                self.audit(
                    db,
                    record["id"],
                    "source_updated" if old else "imported",
                    {
                        "revision": record["revision"],
                        "category": category,
                        "reason": reason,
                    },
                )
            self._rematch(db, rules)
            self.put(db, "sync_cursor", cursor)
            if synced_at is not None:
                self.put(db, "last_successful_sync_at", synced_at)

    def _rematch(self, db, rules):
        changed = 0
        context = db.execute("SELECT value FROM settings WHERE key='splitwise_groups'").fetchone()
        titles = json.loads(context[0]) if context else {}
        for row in db.execute("SELECT * FROM expenses").fetchall():
            record = json.loads(row["payload"])
            if not record["excluded"] and row["reason"] in {"human", "source_changed"}:
                continue
            category, reason = classify(record, rules, titles.get(str(record.get("group_id")), ""))
            if (
                row["reason"] in {"gemini", "historical_fallback"}
                and not record["excluded"]
                and category is None
                and reason != "conflicting_rules"
            ):
                continue
            if category == row["category"] and reason == row["reason"]:
                continue
            db.execute(
                "UPDATE expenses SET category=?,reason=? WHERE id=?", (category, reason, row["id"])
            )
            self.audit(db, row["id"], "category_matched", {"category": category, "reason": reason})
            changed += 1
        return changed

    def reclassify(self, policy=None):
        """Upgrade matching on existing imports while preserving explicit human decisions."""
        with self.transaction() as db:
            rules = [json.loads(r[0]) for r in db.execute("SELECT payload FROM rules")]
            changed = self._rematch(db, rules)
            if policy:
                # Retry only automatic historical fallbacks lacking a decision for this policy.
                # Human choices, remembered rules and successful AI categories remain intact.
                rows = db.execute(
                    """SELECT e.id FROM expenses e WHERE e.reason='historical_fallback'
                    AND NOT EXISTS (SELECT 1 FROM ai_decisions a WHERE a.expense_id=e.id
                    AND a.revision=e.revision AND a.policy=?)""",
                    (policy,),
                ).fetchall()
                for row in rows:
                    db.execute(
                        "UPDATE expenses SET category=NULL,reason='needs_review' WHERE id=?",
                        (row["id"],),
                    )
                    self.audit(db, row["id"], "category_policy_retry", {"policy": policy})
                changed += len(rows)
            return changed

    def expenses(self) -> list[dict]:
        with self.transaction() as db:
            return [
                dict(json.loads(row["payload"]), category=row["category"], reason=row["reason"])
                for row in db.execute("SELECT * FROM expenses ORDER BY id DESC")
            ]

    def begin_history(self):
        """Freeze the first import by source ID, so later backdated purchases are still new.

        Existing accounts freeze their current ledger before the next incremental sync.
        Empty accounts wait until a complete initial fetch has been saved.
        """
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM settings WHERE key='history_initialized'").fetchone():
                return
            if not db.execute("SELECT 1 FROM settings WHERE key='sync_cursor'").fetchone():
                return
            db.execute("INSERT OR IGNORE INTO historical_expenses SELECT id FROM expenses")
            self.put(db, "history_initialized", True)

    def finish_history(self, policy):
        """Only an actual uncertain AI decision permits the historical fallback.

        Failed requests and items still waiting for Gemini remain pending, not guessed.
        Human decisions and known categories are never changed.
        """
        with self.transaction() as db:
            rows = db.execute(
                """SELECT e.id FROM expenses e JOIN historical_expenses h ON h.id=e.id
                JOIN ai_decisions a ON a.expense_id=e.id AND a.revision=e.revision
                WHERE e.category IS NULL AND a.policy=? AND a.category IS NULL
                AND e.reason NOT IN ('human','source_changed','conflicting_rules')""",
                (policy,),
            ).fetchall()
            for row in rows:
                db.execute(
                    "UPDATE expenses SET category=?,reason='historical_fallback' WHERE id=?",
                    (Category.OTHERS.value, row["id"]),
                )
                self.audit(
                    db,
                    row["id"],
                    "historical_fallback",
                    {"category": Category.OTHERS.value, "policy": policy},
                )
            return len(rows)

    def historical_ids(self):
        with self.transaction() as db:
            return {r[0] for r in db.execute("SELECT id FROM historical_expenses")}

    def ai_pending(self, policy, limit=None):
        """Group equivalent pending purchases within this account only; never retry a revision."""
        with self.transaction() as db:
            attempted = {
                (r[0], r[1])
                for r in db.execute(
                    "SELECT expense_id,revision FROM ai_decisions WHERE policy=?", (policy,)
                )
            }
        groups = {}
        for row in self.expenses():
            if (
                row["excluded"]
                or row["category"] is not None
                or row["reason"] in {"human", "source_changed", "conflicting_rules"}
                or (row["id"], row["revision"]) in attempted
            ):
                continue
            key = (
                normalize_description(row["description"]),
                row["group_id"],
                row["currency"],
                (row.get("source_category") or {}).get("name", ""),
            )
            if key not in groups and limit is not None and len(groups) >= limit:
                continue
            groups.setdefault(key, []).append(row)
        return list(groups.values())

    def apply_ai_decisions(self, groups, decisions, policy, model):
        import time

        matched = review = 0
        with self.transaction() as db:
            for decision in decisions:
                category = (
                    decision.category.value if decision.certain and decision.category else None
                )
                for original in groups[decision.item]:
                    row = db.execute(
                        "SELECT * FROM expenses WHERE id=?", (original["id"],)
                    ).fetchone()
                    # A review, remembered rule or source edit during the network call wins.
                    if (
                        not row
                        or row["revision"] != original["revision"]
                        or row["category"]
                        or row["reason"] in {"human", "source_changed", "conflicting_rules"}
                        or json.loads(row["payload"])["excluded"]
                    ):
                        continue
                    db.execute(
                        "INSERT OR REPLACE INTO ai_decisions VALUES (?,?,?,?,?,?,?)",
                        (
                            row["id"],
                            row["revision"],
                            policy,
                            category,
                            decision.reason,
                            model,
                            time.time(),
                        ),
                    )
                    if category:
                        db.execute(
                            "UPDATE expenses SET category=?,reason='gemini' WHERE id=?",
                            (category, row["id"]),
                        )
                        matched += 1
                    else:
                        review += 1
                    self.audit(
                        db,
                        row["id"],
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

    def review(self, expense_id: int, revision: str, category: Category, remember: bool):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM expenses WHERE id=?", (expense_id,)).fetchone()
            if not row:
                raise KeyError(expense_id)
            if row["revision"] != revision:
                raise ConflictError("Expense changed; reload before categorizing")
            record = json.loads(row["payload"])
            if record["excluded"]:
                raise ConflictError("Settled, deleted or zero-share expenses cannot be categorized")
            db.execute(
                "UPDATE expenses SET category=?, reason='human' WHERE id=?",
                (category.value, expense_id),
            )
            if remember:
                description = normalize_description(record["description"])
                if not description:
                    raise ConflictError("Cannot remember an empty description")
                db.execute(
                    "INSERT INTO rules(payload) VALUES (?)",
                    (
                        json.dumps(
                            {
                                "description": description,
                                "group_id": record["group_id"],
                                "currency": record["currency"],
                                "category": category.value,
                            }
                        ),
                    ),
                )
            self.audit(
                db,
                expense_id,
                "human_review",
                {
                    "previous_category": row["category"],
                    "category": category.value,
                    "revision": revision,
                    "remember": remember,
                },
            )
            if remember:
                rules = [json.loads(r[0]) for r in db.execute("SELECT payload FROM rules")]
                self._rematch(db, rules)
