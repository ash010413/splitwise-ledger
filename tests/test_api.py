from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from splitwise_ledger.api import Settings, create_app
from splitwise_ledger.domain import normalize_expense


class FakeProvider:
    async def authorize_url(self, state):
        return "https://secure.splitwise.com/oauth/authorize?state=" + state

    async def exchange(self, code):
        assert code == "valid-code"
        return {"access_token": "private-provider-token"}

    async def current_user(self, token):
        return 7

    async def fetch(self, token, user_id, cursor):
        return [
            normalize_expense(
                {
                    "id": 1,
                    "description": "Costco",
                    "date": "2026-10-25T12:00:00Z",
                    "currency_code": "USD",
                    "cost": "25.00",
                    "users": [{"user_id": 7, "owed_share": "12.50"}],
                },
                user_id,
            )
        ], "2026-10-25T13:00:00+00:00"


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        _env_file=None,
        app_api_token="a" * 32,
        token_encryption_key=Fernet.generate_key().decode(),
        database_path=str(tmp_path / "ledger.db"),
        splitwise_client_id="test",
        splitwise_client_secret="secret",
    )
    with TestClient(create_app(settings, FakeProvider())) as client:
        yield client


AUTH = {"Authorization": "Bearer " + "a" * 32}


def connect(client):
    link = client.post("/oauth/splitwise/start", headers=AUTH).json()["connection_url"]
    state = parse_qs(urlparse(link).query)["ticket"][0]
    client.get(link, follow_redirects=False)
    return state


def test_private_routes_require_auth(client):
    assert client.get("/expenses").status_code == 401
    assert client.post("/sync").status_code == 401
    assert client.post("/oauth/splitwise/start").status_code == 401


def test_oauth_state_cookie_required_and_state_is_one_use(client):
    state = connect(client)
    assert client.get("/oauth/splitwise/callback?state=wrong&code=valid-code").status_code == 400
    response = client.get(f"/oauth/splitwise/callback?state={state}&code=valid-code")
    assert response.status_code == 200
    assert "private-provider-token" not in response.text
    assert client.get(f"/oauth/splitwise/callback?state={state}&code=valid-code").status_code == 400


def test_login_csrf_without_browser_cookie_is_rejected(client):
    state = connect(client)
    client.cookies.clear()
    assert client.get(f"/oauth/splitwise/callback?state={state}&code=valid-code").status_code == 400


def test_sync_review_and_decimal_summary(client):
    state = connect(client)
    client.get(f"/oauth/splitwise/callback?state={state}&code=valid-code")
    assert client.post("/sync", headers=AUTH).status_code == 200
    assert client.post("/sync", headers=AUTH).status_code == 200
    rows = client.get("/expenses?pending_only=true", headers=AUTH).json()
    assert len(rows) == 1
    summary = client.get("/summary", headers=AUTH).json()
    assert summary[0]["amount"] == "12.50"
    assert summary[0]["category"] == "Pending categorization"
    body = {"revision": rows[0]["revision"], "category": "Groceries"}
    assert client.post("/expenses/1/review", json=body, headers=AUTH).status_code == 200
    assert client.get("/expenses?pending_only=true", headers=AUTH).json() == []


def test_tokens_are_encrypted_at_rest(client, tmp_path):
    state = connect(client)
    client.get(f"/oauth/splitwise/callback?state={state}&code=valid-code")
    assert b"private-provider-token" not in (tmp_path / "ledger.db").read_bytes()
