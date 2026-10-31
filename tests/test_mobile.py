"""OAuth handoff, per-account isolation, revocation and exact-share sync checks."""

import time
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from splitwise_ledger.api import Settings, create_app
from splitwise_ledger.domain import Category, normalize_expense
from splitwise_ledger.store import Store


class Provider:
    fail = False
    changed = False
    deleted = False

    def __init__(self):
        self.fetch_calls = 0

    async def authorize_url(self, state):
        return "https://secure.splitwise.com/oauth/authorize?state=" + state

    async def exchange(self, code):
        return {"access_token": "provider-secret-" + code}

    async def current_user(self, token):
        return int(token["access_token"].rsplit("-", 1)[1])

    async def fetch(self, token, user_id, cursor):
        self.fetch_calls += 1
        if self.fail:
            response = httpx.Response(403, request=httpx.Request("GET", "https://test"))
            response.raise_for_status()
        # Same source expense ID visible to two users, entered by a third person.
        return [
            normalize_expense(
                {
                    "id": 42,
                    "description": "Purchase edited" if self.changed else "Purchase",
                    "date": "2026-10-01T10:00:00Z",
                    "currency_code": "USD",
                    "cost": "90.00",
                    "created_by": {"id": 99},
                    "deleted_at": "2026-10-02" if self.deleted else None,
                    "users": [
                        {"user_id": 7, "owed_share": "30.00", "paid_share": "90.00"},
                        {"user_id": 8, "owed_share": "20.00", "paid_share": "0.00"},
                    ],
                },
                user_id,
            )
        ], "2026-10-03T00:00:00+00:00"


@pytest.fixture
def setup(tmp_path):
    settings = Settings(
        _env_file=None,
        app_api_token="a" * 32,
        token_encryption_key=Fernet.generate_key().decode(),
        database_path=str(tmp_path / "mobile.db"),
        daily_sync_enabled=False,
        splitwise_client_id="test",
        splitwise_client_secret="secret",
    )
    provider = Provider()
    with TestClient(create_app(settings, provider)) as client:
        yield client, provider, settings


def begin(client):
    response = client.post("/mobile/auth/start")
    assert response.status_code == 200
    body = response.json()
    client.get(body["connection_path"], follow_redirects=False)
    return body


def login(client, user=7):
    handoff = begin(client)
    response = client.get(
        "/oauth/splitwise/callback",
        params={
            "state": handoff["state"],
            "code": str(user),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "minto://oauth/complete"
    assert "provider-secret" not in response.text
    response = client.post(
        "/mobile/auth/exchange",
        json={
            "state": handoff["state"],
            "verifier": handoff["verifier"],
        },
    )
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_sessions_and_personal_shares_are_isolated(setup):
    client, _, settings = setup
    a, b = login(client, 7), login(client, 8)
    for headers, expected in [(a, "30.00"), (b, "20.00")]:
        assert client.post("/mobile/sync?force=true", headers=headers).status_code == 200
        rows = client.get("/mobile/expenses", headers=headers).json()["expenses"]
        assert len(rows) == 1
        assert rows[0]["my_share"] == expected
        assert rows[0]["category"] is None
    row = client.get("/mobile/expenses", headers=a).json()["expenses"][0]
    assert (
        client.post(
            "/mobile/expenses/42/review",
            headers=a,
            json={
                "revision": row["revision"],
                "category": "Food / Dining",
            },
        ).status_code
        == 200
    )
    assert client.get("/mobile/expenses", headers=b).json()["expenses"][0]["category"] is None
    assert client.get("/expenses", headers=a).status_code == 401
    assert (
        client.get("/mobile/expenses", headers={"Authorization": "Bearer " + "a" * 32}).status_code
        == 401
    )
    assert client.post("/mobile/auth/logout", headers=a).status_code == 200
    assert client.get("/mobile/expenses", headers=a).status_code == 401
    assert client.get("/mobile/expenses", headers=b).status_code == 200
    raw = Path(settings.database_path).read_bytes()
    assert a["Authorization"].split()[1].encode() not in raw
    assert b"provider-secret" not in raw


def test_handoff_requires_cookie_verifier_and_is_one_use(setup):
    client, _, settings = setup
    handoff = begin(client)
    body = {"state": handoff["state"], "verifier": handoff["verifier"]}
    assert client.post("/mobile/auth/exchange", json=body).status_code == 409
    client.cookies.clear()
    path = "/oauth/splitwise/callback"
    params = {"state": handoff["state"], "code": "7"}
    assert client.get(path, params=params, follow_redirects=False).status_code == 400
    client.get(handoff["connection_path"], follow_redirects=False)
    assert client.get(path, params=params, follow_redirects=False).status_code == 302
    assert client.get(path, params=params, follow_redirects=False).status_code == 400
    assert (
        client.post("/mobile/auth/exchange", json=body | {"verifier": "x" * 40}).status_code == 400
    )
    assert client.post("/mobile/auth/exchange", json=body).status_code == 200
    assert client.post("/mobile/auth/exchange", json=body).status_code == 400
    handoff = begin(client)
    with Store(settings.database_path).transaction() as db:
        db.execute("UPDATE mobile_logins SET expires=?", (time.time() - 1,))
    assert (
        client.post(
            "/mobile/auth/exchange",
            json={
                "state": handoff["state"],
                "verifier": handoff["verifier"],
            },
        ).status_code
        == 400
    )


def test_sync_failure_retains_data_and_edits_invalidate_review(setup):
    client, provider, _ = setup
    headers = login(client)
    assert client.post("/mobile/sync?force=true", headers=headers).status_code == 200
    first = client.get("/mobile/expenses", headers=headers).json()
    provider.fail = True
    assert client.post("/mobile/sync?force=true", headers=headers).status_code == 403
    assert client.get("/mobile/expenses", headers=headers).json() == first
    provider.fail = False
    row = first["expenses"][0]
    review = {"revision": row["revision"], "category": "Food / Dining"}
    assert (
        client.post("/mobile/expenses/42/review", headers=headers, json=review).status_code == 200
    )
    provider.changed = True
    assert client.post("/mobile/sync?force=true", headers=headers).status_code == 200
    assert client.get("/mobile/expenses", headers=headers).json()["expenses"][0]["category"] is None
    assert (
        client.post("/mobile/expenses/42/review", headers=headers, json=review).status_code == 409
    )
    provider.deleted = True
    assert client.post("/mobile/sync?force=true", headers=headers).status_code == 200
    assert client.get("/mobile/expenses", headers=headers).json()["expenses"] == []


def test_mobile_analysis_requires_session_and_has_account_scoped_cache(setup, monkeypatch):
    from splitwise_ledger import api

    client, _, settings = setup
    settings.gemini_api_key = "test"
    calls = []

    async def summarize(*args):
        calls.append(1)
        return "Summary"

    monkeypatch.setattr(api, "summarize", summarize)
    body = {"current": {"month": "2026-10", "amounts": {c.value: "1.00" for c in Category}}}
    assert client.post("/mobile/analysis", json=body).status_code == 401
    a, b = login(client, 7), login(client, 8)
    for headers in [a, a, b]:
        assert client.post("/mobile/analysis", headers=headers, json=body).status_code == 200
    assert len(calls) == 2


def test_expired_app_session_and_private_response_headers(setup):
    client, _, settings = setup
    headers = login(client)
    response = client.get("/mobile/account", headers=headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    with Store(settings.database_path).transaction() as db:
        db.execute("UPDATE mobile_sessions SET expires=?", (time.time() - 1,))
    assert client.get("/mobile/account", headers=headers).status_code == 401


def test_gemini_matching_failure_does_not_block_expense_sync(setup, monkeypatch):
    from splitwise_ledger import mobile

    client, _, settings = setup
    settings.gemini_api_key = "test"
    calls = []

    async def unavailable(*args):
        calls.append(1)
        raise httpx.ReadTimeout("test timeout")

    monkeypatch.setattr(mobile, "categorize_pending", unavailable)
    headers = login(client)
    assert client.post("/mobile/sync?force=true", headers=headers).status_code == 200
    response = client.get("/mobile/expenses", headers=headers).json()
    assert len(response["expenses"]) == 1
    assert response["category_warning"]
    assert client.post("/mobile/categories/auto", headers=headers).status_code == 429
    assert len(calls) == 1


def test_daily_sync_skips_fresh_data_but_manual_sync_always_fetches(setup):
    client, provider, settings = setup
    headers = login(client)
    assert client.post("/mobile/sync", headers=headers).status_code == 200
    assert provider.fetch_calls == 1
    for _ in range(3):
        response = client.post("/mobile/sync", headers=headers)
        assert response.status_code == 200
        assert response.json()["skipped"] is True
    assert provider.fetch_calls == 1
    assert client.post("/mobile/sync?force=true", headers=headers).status_code == 200
    assert provider.fetch_calls == 2
    # The daily timestamp is persisted and survives a backend restart.
    fresh_provider = Provider()
    with TestClient(create_app(settings, fresh_provider)) as restarted:
        assert restarted.post("/mobile/sync", headers=headers).json()["skipped"] is True
        assert fresh_provider.fetch_calls == 0


def test_daily_worker_fetches_due_accounts_and_does_not_repeat(setup):
    client, provider, _ = setup
    login(client)
    client.portal.call(client.app.state.run_daily_sync)
    assert provider.fetch_calls == 1
    client.portal.call(client.app.state.run_daily_sync)
    assert provider.fetch_calls == 1


def test_failed_manual_sync_keeps_last_successful_daily_timestamp(setup):
    from splitwise_ledger.mobile import MobileAccounts

    client, provider, settings = setup
    headers = login(client)
    client.post("/mobile/sync", headers=headers)
    accounts = MobileAccounts(
        Store(settings.database_path), Fernet(settings.token_encryption_key.encode())
    )
    ledger = accounts.ledger(7)
    previous = ledger.get("last_successful_sync_at")
    with ledger.transaction() as db:
        ledger.put(db, "last_successful_sync_at", time.time() - 86401)
    due_timestamp = ledger.get("last_successful_sync_at")
    assert due_timestamp < previous
    provider.fail = True
    assert client.post("/mobile/sync?force=true", headers=headers).status_code == 403
    assert ledger.get("last_successful_sync_at") == due_timestamp
    provider.fail = False
    assert client.post("/mobile/sync", headers=headers).status_code == 200
    assert ledger.get("last_successful_sync_at") > due_timestamp


def test_profile_is_account_scoped_and_cached(setup):
    client, provider, _ = setup
    calls = []

    async def profile(token):
        user = await provider.current_user(token)
        calls.append(user)
        return {"user_id": user, "name": f"Test {user}", "email": f"user{user}@example.com"}

    provider.current_profile = profile
    a, b = login(client, 7), login(client, 8)
    assert client.get("/mobile/account", headers=a).json()["profile"]["name"] == "Test 7"
    assert client.get("/mobile/account", headers=b).json()["profile"]["name"] == "Test 8"
    assert calls == [7, 8]
    assert client.get("/mobile/account").status_code == 401


def test_first_import_does_not_prompt_but_new_expenses_do(setup):
    client, _, settings = setup
    headers = login(client)
    client.post("/mobile/sync?force=true", headers=headers)
    row = client.get("/mobile/expenses", headers=headers).json()["expenses"][0]
    assert row["review_required"] is False
    ledger = Store(str(Path(settings.database_path).with_suffix("")) + "-accounts/7.sqlite3")
    ledger.save_batch([dict(row, id=99, revision="new")], "later")
    rows = client.get("/mobile/expenses", headers=headers).json()["expenses"]
    assert rows[0]["review_required"] is True


def test_daily_worker_sends_entire_historical_backlog_to_gemini_before_fallback(setup, monkeypatch):
    import json

    from splitwise_ledger.categorization import POLICY_VERSION

    client, _, settings = setup
    headers = login(client)
    client.post("/mobile/sync", headers=headers)
    ledger = Store(str(Path(settings.database_path).with_suffix("")) + "-accounts/7.sqlite3")
    template = ledger.expenses()[0]
    # Simulate an existing account upgrading with 45 distinct historical descriptions.
    with ledger.transaction() as db:
        db.execute("DELETE FROM settings WHERE key='history_initialized'")
    ledger.save_batch(
        [
            dict(template, id=i, description=f"Unknown merchant {i}", revision=f"r{i}")
            for i in range(100, 144)
        ],
        "later",
    )
    settings.gemini_api_key = "test"
    calls = []
    real = httpx.AsyncClient

    def handle(req):
        body = json.loads(req.content)
        items = json.loads(body["contents"][0]["parts"][0]["text"])
        calls.append(len(items))
        decisions = [
            {
                "item": r["item"],
                "category": "Needs review",
                "certain": False,
                "reason": "Unknown purpose",
            }
            for r in items
        ]
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": json.dumps({"decisions": decisions})}]},
                    }
                ]
            },
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handle), **kw)
    )
    client.portal.call(client.app.state.run_daily_sync)
    assert calls == [40, 5]
    rows = client.get("/mobile/expenses", headers=headers).json()["expenses"]
    assert len(rows) == 45
    assert all(r["category"] == "Others" and r["review_required"] is False for r in rows)
    assert not ledger.ai_pending(POLICY_VERSION)
    # An uncertain purchase added later must pass through Gemini and then request review.
    ledger.save_batch(
        [dict(template, id=999, revision="new", date="2020-01-01T00:00:00Z")], "later"
    )
    assert (
        client.get("/mobile/expenses", headers=headers).json()["expenses"][0]["review_required"]
        is False
    )
    assert client.post("/mobile/categories/auto", headers=headers).status_code == 200
    row = client.get("/mobile/expenses", headers=headers).json()["expenses"][0]
    assert row["category"] is None
    assert row["review_required"] is True


def test_group_context_refresh_is_account_scoped_and_not_an_expense_revision(setup):
    client, provider, settings = setup
    calls = []

    async def groups(token):
        user = await provider.current_user(token)
        calls.append(user)
        return {"9": "Spotify Family" if user == 7 else "Friends"}

    provider.groups = groups
    a, b = login(client, 7), login(client, 8)
    client.post("/mobile/sync", headers=a)
    original = client.get("/mobile/expenses", headers=a).json()["expenses"][0]
    assert client.post("/mobile/sync", headers=a).json()["skipped"] is True
    assert calls == [7]
    client.post("/mobile/sync", headers=b)
    assert calls == [7, 8]
    root = str(Path(settings.database_path).with_suffix("")) + "-accounts/"
    assert Store(root + "7.sqlite3").get("splitwise_groups") == {"9": "Spotify Family"}
    assert Store(root + "8.sqlite3").get("splitwise_groups") == {"9": "Friends"}
    client.post("/mobile/sync?force=true", headers=a)
    assert calls == [7, 8, 7]
    actual = client.get("/mobile/expenses", headers=a).json()["expenses"][0]
    assert actual["revision"] == original["revision"]
    assert actual["my_share"] == original["my_share"]


def test_group_lookup_failure_preserves_expenses_and_can_retry(setup):
    client, provider, settings = setup

    async def fail(token):
        raise httpx.ReadTimeout("timeout")

    provider.groups = fail
    headers = login(client)
    assert client.post("/mobile/sync?force=true", headers=headers).status_code == 200
    actual = client.get("/mobile/expenses", headers=headers).json()
    assert len(actual["expenses"]) == 1
    assert actual["sync_warning"]
