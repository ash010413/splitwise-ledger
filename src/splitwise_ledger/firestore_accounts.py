"""Firestore OAuth/session repository and cross-revision operation leases."""

import json
import secrets
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import HTTPException
from google.cloud import firestore

from .firestore_ledger import CURRENT_OPERATION, FirestoreLedger
from .mobile import digest


class FirestoreAccounts:
    def __init__(self, client, cipher, max_accounts=4):
        self.client, self.cipher, self.max_accounts = client, cipher, max_accounts

    def ref(self, collection, key):
        return self.client.collection("minto_" + collection).document(str(key))

    def ledger(self, user_id):
        return FirestoreLedger(self.client, user_id)

    def start_login(self, state, verifier):
        self.ref("logins", state).create(
            {
                "verifier": digest(verifier),
                "expires": time.time() + 600,
                "user_id": None,
                "claimed": False,
            }
        )

    def login(self, state):
        return self.ref("logins", state).get().to_dict()

    def claim_login(self, state, cookie):
        @firestore.transactional
        def claim(tx):
            ref = self.ref("logins", state)
            row = ref.get(transaction=tx).to_dict()
            if not row or row["expires"] < time.time() or row["claimed"] or cookie != state:
                raise HTTPException(400, "Invalid or expired sign-in; start again")
            tx.update(ref, {"claimed": True})

        claim(self.client.transaction())

    def complete_login(self, state, user_id, token):
        encrypted = self.cipher.encrypt(json.dumps(token).encode()).decode()

        @firestore.transactional
        def complete(tx):
            login = self.ref("logins", state)
            attempt = login.get(transaction=tx).to_dict()
            control = self.ref("control", "admission")
            admission = control.get(transaction=tx).to_dict() or {"users": []}
            if not attempt or not attempt["claimed"] or attempt["expires"] < time.time():
                raise HTTPException(400, "Expired sign-in; start again")
            users = admission["users"]
            if user_id not in users:
                if len(users) >= self.max_accounts:
                    raise HTTPException(403, "This private beta is full. Contact the app owner.")
                tx.set(control, {"users": users + [user_id]})
            tx.set(self.ref("users", user_id), {"token": encrypted})
            tx.update(login, {"user_id": user_id})

        complete(self.client.transaction())

    def exchange_login(self, body, session):
        @firestore.transactional
        def exchange(tx):
            ref = self.ref("logins", body.state)
            row = ref.get(transaction=tx).to_dict()
            if (
                not row
                or row["expires"] < time.time()
                or not secrets.compare_digest(row["verifier"], digest(body.verifier))
            ):
                raise HTTPException(400, "Invalid sign-in handoff")
            if row["user_id"] is None:
                raise HTTPException(409, "Finish authorizing in Splitwise first")
            tx.delete(ref)
            tx.set(
                self.ref("sessions", digest(session)),
                {"user_id": row["user_id"], "expires": time.time() + 30 * 86400},
            )
            return row["user_id"]

        return exchange(self.client.transaction())

    def user(self, token):
        row = self.ref("sessions", digest(token)).get().to_dict()
        if not row or row["expires"] <= time.time():
            raise HTTPException(401, "Sign in to Splitwise again")
        return row["user_id"]

    def logout(self, token):
        self.ref("sessions", digest(token)).delete()

    def token(self, user_id):
        row = self.ref("users", user_id).get().to_dict()
        return json.loads(self.cipher.decrypt(row["token"].encode())) if row else None

    def users(self):
        return [int(row.id) for row in self.client.collection("minto_users").stream()]

    @asynccontextmanager
    async def operation(self, user_id):
        owner = uuid.uuid4().hex
        ref = self.ref("leases", user_id)

        @firestore.transactional
        def acquire(tx):
            row = ref.get(transaction=tx).to_dict() or {}
            if row.get("expires", 0) > time.time():
                raise HTTPException(409, "Sync or category matching is already running")
            tx.set(ref, {"owner": owner, "expires": time.time() + 1200})

        acquire(self.client.transaction())
        handle = CURRENT_OPERATION.set((int(user_id), owner))
        try:
            yield
        finally:
            CURRENT_OPERATION.reset(handle)

            @firestore.transactional
            def release(tx):
                row = ref.get(transaction=tx).to_dict() or {}
                if row.get("owner") == owner:
                    tx.delete(ref)

            release(self.client.transaction())
