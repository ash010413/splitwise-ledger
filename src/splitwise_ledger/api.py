"""Composition root and authenticated HTTP boundary for the single-user prototype."""

import asyncio
import json
import secrets
import time
from decimal import Decimal

import httpx
from authlib.integrations.base_client.errors import OAuthError
from authlib.oauth2.rfc6749 import OAuth2Error
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .analysis import AnalysisRequest, summarize
from .domain import Category
from .splitwise import SplitwiseClient
from .store import ConflictError, Store


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    splitwise_client_id: str = ""
    splitwise_client_secret: str = ""
    splitwise_redirect_uri: str = "http://127.0.0.1:8000/oauth/splitwise/callback"
    app_api_token: str = Field(min_length=32)
    token_encryption_key: str
    database_path: str = "data/ledger.sqlite3"
    gemini_api_key: str = ""
    gemini_model: str = Field(default="gemini-3.8-flash", pattern=r"^[a-zA-Z0-9.-]+$")


class Review(BaseModel):
    revision: str
    category: Category
    remember_rule: bool = False


def oauth_failure(stage: str, error: Exception) -> str:
    """Describe only allowlisted metadata; provider error bodies may contain secrets."""
    if isinstance(error, httpx.HTTPStatusError):
        return f"Splitwise {stage} failed (HTTP {error.response.status_code}). Restart connection."
    if isinstance(error, httpx.RequestError):
        return f"Splitwise {stage} failed: network connection or timeout. Restart connection."
    code = getattr(error, "error", None)
    if code in {
        "invalid_client",
        "invalid_grant",
        "invalid_request",
        "unauthorized_client",
        "access_denied",
        "unsupported_grant_type",
    }:
        return f"Splitwise {stage} failed ({code}). Check client credentials and callback URL."
    return f"Splitwise {stage} failed: invalid provider response. Restart connection."


def create_app(settings: Settings | None = None, provider=None) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.database_path)
    cipher = Fernet(settings.token_encryption_key.encode())
    provider = provider or SplitwiseClient(
        settings.splitwise_client_id,
        settings.splitwise_client_secret,
        settings.splitwise_redirect_uri,
    )
    app = FastAPI(title="Splitwise Ledger", version="0.1.0")
    lock = asyncio.Lock()
    analysis_lock = asyncio.Lock()
    analysis_cache = {}
    bearer = HTTPBearer(auto_error=False)

    def authenticated(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),  # noqa: B008
    ):
        if not credentials or not secrets.compare_digest(
            credentials.credentials, settings.app_api_token
        ):
            raise HTTPException(401, "Valid application bearer token required")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/analysis", dependencies=[Depends(authenticated)])
    async def analyze(body: AnalysisRequest):
        if not settings.gemini_api_key:
            raise HTTPException(503, "Add GEMINI_API_KEY to the backend .env and restart it.")
        fingerprint = body.model_dump_json()
        cached = analysis_cache.get(fingerprint)
        if cached and time.time() - cached["created"] < 300:
            return cached["response"]
        if analysis_lock.locked():
            raise HTTPException(429, "A summary is already being generated. Please wait.")
        async with analysis_lock:
            try:
                result = await summarize(body, settings.gemini_api_key, settings.gemini_model)
            except httpx.HTTPStatusError as exc:
                detail = (
                    f"Gemini request failed (HTTP {exc.response.status_code}). "
                    "Check the backend key and configured model."
                )
                if exc.response.status_code == 429:
                    detail = "Gemini quota or rate limit reached. Try again later."
                raise HTTPException(502, detail) from None
            except httpx.TimeoutException:
                raise HTTPException(502, "Gemini timed out. Please try again later.") from None
            except (httpx.HTTPError, ValueError, KeyError):
                raise HTTPException(
                    502, "Gemini could not return a complete summary. Try again."
                ) from None
            response = {
                "summary": result,
                "month": body.current.month,
                "model": settings.gemini_model,
            }
            analysis_cache.clear()
            analysis_cache[fingerprint] = {"created": time.time(), "response": response}
            return response

    @app.get("/categories", dependencies=[Depends(authenticated)])
    def categories():
        return list(Category)

    @app.post("/oauth/splitwise/start", dependencies=[Depends(authenticated)])
    async def start():
        if not settings.splitwise_client_id or not settings.splitwise_client_secret:
            raise HTTPException(503, "Configure Splitwise OAuth client ID and secret first")
        state = secrets.token_urlsafe(32)
        with store.transaction() as db:
            store.put(db, "oauth_state", {"state": state, "expires": time.time() + 600})
        return {"connection_url": "/oauth/splitwise/connect?ticket=" + state}

    @app.get("/oauth/splitwise/callback", response_class=HTMLResponse)
    async def callback(request: Request, state: str = "", code: str = ""):
        # A browser-bound, one-use state prevents login CSRF / token substitution.
        with store.transaction() as db:
            row = db.execute("SELECT value FROM settings WHERE key='oauth_state'").fetchone()
            expected = json.loads(row[0]) if row else None
            if (
                not expected
                or expected["expires"] < time.time()
                or not secrets.compare_digest(state, expected["state"])
                or request.cookies.get("oauth_state") != state
            ):
                raise HTTPException(400, "Invalid or expired OAuth state; restart connection")
            db.execute("DELETE FROM settings WHERE key='oauth_state'")
        if request.query_params.get("error") or not code:
            raise HTTPException(400, "Splitwise authorization was not completed")
        try:
            token = await provider.exchange(code)
        except (httpx.HTTPError, OAuthError, OAuth2Error, ValueError, KeyError) as exc:
            raise HTTPException(502, oauth_failure("token exchange", exc)) from None
        try:
            user_id = await provider.current_user(token)
        except (httpx.HTTPError, OAuthError, OAuth2Error, ValueError, KeyError) as exc:
            raise HTTPException(502, oauth_failure("account lookup", exc)) from None
        old_user = store.get("user_id")
        if old_user is not None and old_user != user_id:
            raise HTTPException(409, "Different account connected; use a separate database")
        with store.transaction() as db:
            store.put(db, "oauth_token", cipher.encrypt(json.dumps(token).encode()).decode())
            store.put(db, "user_id", user_id)
        response = HTMLResponse(
            "<h1>Splitwise connected</h1><p>Account access verified. "
            "Run Sync now to verify expense access. You can close this tab.</p>",
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
        response.delete_cookie("oauth_state")
        return response

    @app.get("/oauth/splitwise/connect")
    async def connect(ticket: str):
        # The one-time start state is a short-lived browser handoff ticket, not an API token.
        expected = store.get("oauth_state")
        if (
            not expected
            or expected["expires"] < time.time()
            or not secrets.compare_digest(ticket, expected["state"])
        ):
            raise HTTPException(400, "Invalid connection ticket")
        response = RedirectResponse(await provider.authorize_url(ticket))
        response.set_cookie(
            "oauth_state",
            ticket,
            httponly=True,
            samesite="lax",
            max_age=600,
            secure=settings.splitwise_redirect_uri.startswith("https://"),
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.post("/sync", dependencies=[Depends(authenticated)])
    async def sync():
        if lock.locked():
            raise HTTPException(409, "Sync already running")
        async with lock:
            encrypted = store.get("oauth_token")
            if not encrypted:
                raise HTTPException(409, "Connect Splitwise first")
            token = json.loads(cipher.decrypt(encrypted.encode()))
            if token.get("expires_at") and float(token["expires_at"]) <= time.time():
                raise HTTPException(409, "OAuth token expired; reconnect Splitwise")
            try:
                records, cursor = await provider.fetch(
                    token, store.get("user_id"), store.get("sync_cursor")
                )
                store.save_batch(records, cursor)
            except (httpx.HTTPError, ValueError, KeyError):
                raise HTTPException(502, "Expense sync failed; previous records retained") from None
        return {"fetched": len(records), "last_successful_sync": cursor}

    @app.get("/expenses", dependencies=[Depends(authenticated)])
    def expenses(pending_only: bool = False):
        rows = store.expenses()
        return (
            [r for r in rows if not r["excluded"] and not r["category"]] if pending_only else rows
        )

    @app.post("/expenses/{expense_id}/review", dependencies=[Depends(authenticated)])
    def review(expense_id: int, decision: Review):
        try:
            store.review(expense_id, decision.revision, decision.category, decision.remember_rule)
        except KeyError:
            raise HTTPException(404, "Expense not found") from None
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from None
        return {"status": "reviewed"}

    @app.get("/summary", dependencies=[Depends(authenticated)])
    def summary():
        totals = {}
        for row in store.expenses():
            if row["excluded"]:
                continue
            # Source date's calendar month; no silent currency conversion or netting.
            key = (row["date"][:7], row["currency"], row["category"] or "Pending categorization")
            totals[key] = totals.get(key, Decimal("0")) + Decimal(row["my_share"])
        return [
            {"month": k[0], "currency": k[1], "category": k[2], "amount": str(v)}
            for k, v in sorted(totals.items())
        ]

    return app
