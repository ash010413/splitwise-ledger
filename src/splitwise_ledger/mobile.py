"""Small-group OAuth boundary. Each account has its own ledger and revocable sessions.

Use one backend worker for this SQLite beta. Only opaque handoff state reaches the
browser; app sessions are exchanged over the native client's secret channel.
"""

import asyncio
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .categorization import POLICY_VERSION, categorize_pending
from .store import ConflictError, Store


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Handoff(BaseModel):
    state: str = Field(min_length=32, max_length=200)
    verifier: str = Field(min_length=32, max_length=200)


class MobileAccounts:
    def __init__(self, store, cipher):
        self.store, self.cipher = store, cipher
        self.root = Path(store.path).parent / (Path(store.path).stem + "-accounts")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with store.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS mobile_accounts (
                    user_id INTEGER PRIMARY KEY, token TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mobile_sessions (
                    digest TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mobile_logins (
                    state TEXT PRIMARY KEY, verifier TEXT NOT NULL, expires REAL NOT NULL,
                    user_id INTEGER, claimed INTEGER NOT NULL DEFAULT 0
                );
            """)

    def ledger(self, user_id):
        return Store(str(self.root / f"{int(user_id)}.sqlite3"))

    def user(self, token):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT user_id FROM mobile_sessions WHERE digest=? AND expires>?",
                (digest(token), time.time()),
            ).fetchone()
        if not row:
            raise HTTPException(401, "Sign in to Splitwise again")
        return row["user_id"]


def mobile_router(settings, provider, accounts, analysis, review_type, oauth_failure):
    router = APIRouter(prefix="/mobile")
    bearer = HTTPBearer(auto_error=False)
    locks = {}

    def authenticated(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if not credentials:
            raise HTTPException(401, "Sign in to Splitwise")
        return accounts.user(credentials.credentials)

    require_user = Depends(authenticated)

    async def match_categories(ledger):
        if not settings.gemini_api_key or not settings.gemini_auto_categorize:
            raise HTTPException(503, "Automatic category matching is not enabled")
        if (ledger.get("category_retry_after") or 0) > time.time():
            raise HTTPException(429, "Category matching will retry shortly. Expenses are synced.")
        try:
            result = await categorize_pending(
                ledger, settings.gemini_api_key, settings.gemini_model
            )
            ledger.finish_history(POLICY_VERSION)
        except (httpx.HTTPError, ValueError, KeyError):
            warning = "Gemini category matching is temporarily unavailable. Expenses are synced."
            with ledger.transaction() as db:
                ledger.put(db, "category_warning", warning)
                ledger.put(db, "category_retry_after", time.time() + 300)
            raise HTTPException(502, warning) from None
        with ledger.transaction() as db:
            ledger.put(db, "category_warning", None)
            ledger.put(db, "category_retry_after", 0)
        return result

    @router.post("/auth/start")
    async def start():
        if not settings.splitwise_client_id or not settings.splitwise_client_secret:
            raise HTTPException(503, "Splitwise OAuth is not configured on the server")
        state, verifier = "minto_" + secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with accounts.store.transaction() as db:
            db.execute("DELETE FROM mobile_logins WHERE expires<?", (time.time(),))
            db.execute("DELETE FROM mobile_sessions WHERE expires<?", (time.time(),))
            db.execute(
                "INSERT INTO mobile_logins(state,verifier,expires) VALUES (?,?,?)",
                (state, digest(verifier), time.time() + 600),
            )
        return {
            "state": state,
            "verifier": verifier,
            "connection_path": "/mobile/auth/connect?state=" + state,
        }

    @router.get("/auth/connect")
    async def connect(state: str):
        with accounts.store.transaction() as db:
            row = db.execute("SELECT * FROM mobile_logins WHERE state=?", (state,)).fetchone()
            if not row or row["expires"] < time.time() or row["claimed"]:
                raise HTTPException(400, "Expired sign-in; start again")
        response = RedirectResponse(await provider.authorize_url(state))
        response.set_cookie(
            "minto_oauth_state",
            state,
            httponly=True,
            samesite="lax",
            secure=settings.splitwise_redirect_uri.startswith("https://"),
            max_age=600,
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    async def callback(request: Request, state: str, code: str):
        with accounts.store.transaction() as db:
            row = db.execute("SELECT * FROM mobile_logins WHERE state=?", (state,)).fetchone()
            if (
                not row
                or row["expires"] < time.time()
                or row["claimed"]
                or request.cookies.get("minto_oauth_state") != state
            ):
                raise HTTPException(400, "Invalid or expired sign-in; start again")
            db.execute("UPDATE mobile_logins SET claimed=1 WHERE state=?", (state,))
        if not code or request.query_params.get("error"):
            raise HTTPException(400, "Splitwise authorization was cancelled")
        try:
            token = await provider.exchange(code)
            profile = (
                await provider.current_profile(token)
                if hasattr(provider, "current_profile")
                else None
            )
            user_id = profile["user_id"] if profile else await provider.current_user(token)
        except Exception as exc:
            # Same sanitized error mapping as the legacy flow; never return provider bodies.
            raise HTTPException(502, oauth_failure("authorization", exc)) from None
        with accounts.store.transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO mobile_accounts VALUES (?,?)",
                (user_id, accounts.cipher.encrypt(json.dumps(token).encode()).decode()),
            )
            db.execute("UPDATE mobile_logins SET user_id=? WHERE state=?", (user_id, state))
        if profile:
            ledger = accounts.ledger(user_id)
            with ledger.transaction() as db:
                ledger.put(db, "profile", profile)
        response = RedirectResponse("minto://oauth/complete", status_code=302)
        response.delete_cookie("minto_oauth_state")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @router.post("/auth/exchange")
    def exchange(body: Handoff):
        session = secrets.token_urlsafe(48)
        with accounts.store.transaction() as db:
            row = db.execute("SELECT * FROM mobile_logins WHERE state=?", (body.state,)).fetchone()
            if (
                not row
                or row["expires"] < time.time()
                or not secrets.compare_digest(row["verifier"], digest(body.verifier))
            ):
                raise HTTPException(400, "Invalid sign-in handoff")
            if row["user_id"] is None:
                raise HTTPException(409, "Finish authorizing in Splitwise first")
            db.execute("DELETE FROM mobile_logins WHERE state=?", (body.state,))
            db.execute(
                "INSERT INTO mobile_sessions VALUES (?,?,?)",
                (digest(session), row["user_id"], time.time() + 30 * 86400),
            )
        return {"access_token": session, "user_id": row["user_id"]}

    @router.post("/auth/logout")
    def logout(request: Request, user_id=require_user):
        token = request.headers["authorization"].split(" ", 1)[1]
        with accounts.store.transaction() as db:
            db.execute("DELETE FROM mobile_sessions WHERE digest=?", (digest(token),))
        return {"status": "signed_out"}

    @router.get("/account")
    async def account(user_id=require_user):
        ledger = accounts.ledger(user_id)
        if not ledger.get("profile") and hasattr(provider, "current_profile"):
            with accounts.store.transaction() as db:
                row = db.execute(
                    "SELECT token FROM mobile_accounts WHERE user_id=?", (user_id,)
                ).fetchone()
            if row:
                try:
                    profile = await provider.current_profile(
                        json.loads(accounts.cipher.decrypt(row["token"].encode()))
                    )
                    if profile["user_id"] == user_id:
                        with ledger.transaction() as db:
                            ledger.put(db, "profile", profile)
                except (httpx.HTTPError, ValueError, KeyError):
                    pass  # An optional profile must not block access to cached spending.
        return {
            "user_id": user_id,
            "last_successful_sync": ledger.get("sync_cursor"),
            "profile": ledger.get("profile"),
        }

    @router.post("/sync")
    async def sync(force: bool = False, user_id=require_user):
        lock = locks.setdefault(user_id, asyncio.Lock())
        if lock.locked() and not force:
            raise HTTPException(409, "Sync already running")
        async with lock:
            ledger = accounts.ledger(user_id)
            ledger.begin_history()
            last = ledger.get("last_successful_sync_at")
            if last is None and ledger.get("sync_cursor"):
                try:
                    stamp = datetime.fromisoformat(ledger.get("sync_cursor"))
                    last = (
                        stamp.replace(tzinfo=UTC).timestamp()
                        if stamp.tzinfo is None
                        else stamp.timestamp()
                    )
                except ValueError:
                    pass
            if not force and last is not None and 0 <= time.time() - last < 86400:
                return {
                    "fetched": 0,
                    "skipped": True,
                    "last_successful_sync": ledger.get("sync_cursor"),
                }
            with accounts.store.transaction() as db:
                row = db.execute(
                    "SELECT token FROM mobile_accounts WHERE user_id=?", (user_id,)
                ).fetchone()
            if not row:
                raise HTTPException(401, "Reconnect Splitwise")
            token = json.loads(accounts.cipher.decrypt(row["token"].encode()))
            if token.get("expires_at") and float(token["expires_at"]) <= time.time():
                raise HTTPException(401, "Splitwise connection expired; reconnect")
            try:
                records, cursor = await provider.fetch(token, user_id, ledger.get("sync_cursor"))
                ledger.save_batch(records, cursor, synced_at=time.time())
                ledger.begin_history()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403):
                    raise HTTPException(
                        403, "Splitwise denied access. Check Pro or reconnect."
                    ) from None
                raise HTTPException(502, "Splitwise sync failed; existing data retained") from None
            except (httpx.HTTPError, ValueError, KeyError):
                raise HTTPException(502, "Splitwise sync failed; existing data retained") from None
            if settings.gemini_api_key and settings.gemini_auto_categorize:
                try:
                    await match_categories(ledger)
                except HTTPException:
                    pass  # AI availability must never prevent importing actual expenses.
            with ledger.transaction() as db:
                ledger.put(db, "sync_warning", None)
                ledger.put(db, "daily_sync_failed_at", 0)
        return {"fetched": len(records), "last_successful_sync": cursor}

    async def sync_due_accounts():
        with accounts.store.transaction() as db:
            users = [row[0] for row in db.execute("SELECT user_id FROM mobile_accounts")]
        for user_id in users:
            ledger = accounts.ledger(user_id)
            # Failed scheduled requests back off for an hour; manual sync bypasses this.
            if time.time() - (ledger.get("daily_sync_failed_at") or 0) < 3600:
                continue
            try:
                await sync(force=False, user_id=user_id)
                if settings.gemini_api_key and settings.gemini_auto_categorize:
                    # Finish the whole backlog even when the native app is closed.
                    # Each batch remains bounded and revision-safe, and errors back off.
                    while ledger.ai_pending(POLICY_VERSION):
                        try:
                            await auto_categories(user_id=user_id)
                        except HTTPException:
                            break  # Matching has its own status; the expense sync succeeded.
            except HTTPException as exc:
                if exc.status_code == 409:
                    continue
                with ledger.transaction() as db:
                    ledger.put(db, "daily_sync_failed_at", time.time())
                    ledger.put(
                        db,
                        "sync_warning",
                        "Daily sync could not complete. Pull to refresh to retry.",
                    )
            except Exception:
                # One broken account must not stop scheduling for the other users.
                with ledger.transaction() as db:
                    ledger.put(db, "daily_sync_failed_at", time.time())
                    ledger.put(db, "sync_warning", "Daily sync could not complete. Please retry.")

    @router.post("/categories/auto")
    async def auto_categories(user_id=require_user):
        lock = locks.setdefault(user_id, asyncio.Lock())
        if lock.locked():
            raise HTTPException(409, "Category matching or sync is already running")
        async with lock:
            ledger = accounts.ledger(user_id)
            ledger.begin_history()
            return await match_categories(ledger)

    @router.get("/expenses")
    def expenses(user_id=require_user):
        ledger = accounts.ledger(user_id)
        ledger.begin_history()
        ledger.finish_history(POLICY_VERSION)
        historical = ledger.historical_ids()
        auto_enabled = bool(settings.gemini_api_key and settings.gemini_auto_categorize)
        waiting_for_ai = (
            {r["id"] for group in ledger.ai_pending(POLICY_VERSION) for r in group}
            if auto_enabled
            else set()
        )
        return {
            "expenses": [
                dict(
                    r,
                    review_required=(r["id"] not in historical and r["id"] not in waiting_for_ai)
                    or r["reason"] in {"source_changed", "conflicting_rules"},
                )
                for r in ledger.expenses()
                if not r["excluded"]
            ],
            "last_successful_sync": ledger.get("sync_cursor"),
            "auto_enabled": auto_enabled,
            "auto_remaining": len(waiting_for_ai),
            "category_warning": ledger.get("category_warning"),
            "sync_warning": ledger.get("sync_warning"),
        }

    @router.post("/expenses/{expense_id}/review")
    def review(expense_id: int, decision: review_type, user_id=require_user):
        try:
            accounts.ledger(user_id).review(
                expense_id, decision.revision, decision.category, decision.remember_rule
            )
        except KeyError:
            raise HTTPException(404, "Expense not found") from None
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from None
        return {"status": "reviewed"}

    # Per-user authentication also applies to AI. Do not share cached replies across accounts.
    from .analysis import AnalysisRequest

    @router.post("/analysis")
    async def analyze(body: AnalysisRequest, user_id=require_user):
        return await analysis(body, cache_scope=str(user_id))

    return router, callback, sync_due_accounts
