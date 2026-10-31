"""One-time, idempotent migration of local ledgers to the hosted private beta.

Run on the owner's Mac with a signed-in gcloud CLI. Provider credentials stay encrypted;
native sessions are intentionally not transferred to the new server endpoint.
"""

import argparse
import hashlib
import json
import secrets
import subprocess

from google.cloud import firestore
from google.oauth2.credentials import Credentials

from splitwise_ledger.api import Settings
from splitwise_ledger.firestore_ledger import FirestoreLedger, pack
from splitwise_ledger.mobile import MobileAccounts
from splitwise_ledger.store import ConflictError, Store


def import_ledger(source, target):
    with source.transaction() as db:
        settings = {r[0]: json.loads(r[1]) for r in db.execute("SELECT key,value FROM settings")}
        rules = [json.loads(r[0]) for r in db.execute("SELECT payload FROM rules ORDER BY id")]
        historical = {r[0] for r in db.execute("SELECT id FROM historical_expenses")}
        decisions = {}
        for row in db.execute("SELECT * FROM ai_decisions ORDER BY created_at"):
            decisions.setdefault(row["expense_id"], {}).setdefault(row["policy"], {})[
                row["revision"]
            ] = {
                "revision": row["revision"],
                "category": row["category"],
                "reason": row["reason"],
                "model": row["model"],
            }
        records = {}
        for row in db.execute("SELECT * FROM expenses"):
            records[str(row["id"])] = {
                "payload": json.loads(row["payload"]),
                "revision": row["revision"],
                "category": row["category"],
                "reason": row["reason"],
                "historical": row["id"] in historical,
                "ai": {
                    policy: revisions[row["revision"]]
                    for policy, revisions in decisions.get(row["id"], {}).items()
                    if row["revision"] in revisions
                },
            }
        audit = [
            {
                "expense_id": row["expense_id"],
                "action": row["action"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"],
            }
            for row in db.execute("SELECT * FROM audit ORDER BY id")
        ]
    fingerprint = hashlib.sha256(
        pack({"settings": settings, "rules": rules, "records": records}).encode()
    ).hexdigest()

    def update(meta, rows, events):
        if meta["settings"].get("migration_digest") == fingerprint:
            return False
        if rows or meta["settings"].get("sync_cursor"):
            raise ConflictError("Hosted ledger already has data; refusing to overwrite it")
        meta["settings"] = {**settings, "migration_digest": fingerprint}
        meta["rules"] = rules
        rows.update(records)
        events.extend(audit)
        return True

    changed = target._run(update)
    expected = source.expenses()
    actual = target.expenses()
    if changed and actual != expected:
        raise ValueError("Migration verification failed")
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--gcloud", default="gcloud")
    args = parser.parse_args()

    def cloud_output(*command):
        result = subprocess.run(
            [args.gcloud, *command, "--project=" + args.project], capture_output=True, text=True
        )
        if result.returncode:
            raise RuntimeError("Google Cloud command failed; check login and permissions")
        return result.stdout.strip()

    settings = Settings()
    encryption_key = cloud_output(
        "secrets", "versions", "access", "latest", "--secret=minto-encryption-key"
    )
    if not secrets.compare_digest(encryption_key, settings.token_encryption_key):
        raise ValueError(
            "Hosted encryption key differs; migration stopped without transferring tokens"
        )
    token = cloud_output("auth", "print-access-token")
    client = firestore.Client(project=args.project, credentials=Credentials(token))
    from cryptography.fernet import Fernet

    accounts = MobileAccounts(
        Store(settings.database_path), Fernet(settings.token_encryption_key.encode())
    )
    users = accounts.users()
    if len(users) > 4:
        raise ValueError("Private beta capacity exceeded")
    for user in users:
        source = accounts.ledger(user)
        source.begin_history()
        changed = import_ledger(source, FirestoreLedger(client, user))
        with accounts.store.transaction() as db:
            encrypted = db.execute(
                "SELECT token FROM mobile_accounts WHERE user_id=?", (user,)
            ).fetchone()[0]
        client.collection("minto_users").document(str(user)).set({"token": encrypted})
        print(
            "Ledger migrated and verified" if changed else "Ledger already migrated; preserved",
            flush=True,
        )

    @firestore.transactional
    def admit(tx):
        ref = client.collection("minto_control").document("admission")
        prior = ref.get(transaction=tx).to_dict() or {"users": []}
        combined = sorted(set(prior["users"]) | set(users))
        if len(combined) > 4:
            raise ValueError("Private beta capacity exceeded")
        tx.set(ref, {"users": combined})

    admit(client.transaction())
    print(f"Migration complete: {len(users)} accounts. No personal data or credentials printed.")


if __name__ == "__main__":
    main()
