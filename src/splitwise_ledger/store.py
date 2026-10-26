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
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, expense_id INTEGER NOT NULL,
                    action TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
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

    @staticmethod
    def put(db, key, value):
        db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))

    @staticmethod
    def audit(db, expense_id, action, payload):
        db.execute(
            "INSERT INTO audit(expense_id,action,payload,created_at) VALUES (?,?,?,?)",
            (expense_id, action, json.dumps(payload), datetime.now(UTC).isoformat()),
        )

    def save_batch(self, records: list[dict], cursor: str):
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
            self.put(db, "sync_cursor", cursor)

    def expenses(self) -> list[dict]:
        with self.transaction() as db:
            return [
                dict(json.loads(row["payload"]), category=row["category"], reason=row["reason"])
                for row in db.execute("SELECT * FROM expenses ORDER BY id DESC")
            ]

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
