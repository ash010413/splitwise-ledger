import asyncio

import httpx
import pytest

from splitwise_ledger.splitwise import SplitwiseClient


def test_incremental_pagination_and_overlap(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer token"
        if request.url.params["offset"] == "0":
            return httpx.Response(
                200,
                json={
                    "expenses": [
                        {
                            "id": 5,
                            "description": "Rent",
                            "date": "2026-10-01T00:00:00Z",
                            "currency_code": "USD",
                            "cost": "1000",
                            "users": [{"user_id": 7, "owed_share": "500"}],
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"expenses": []})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(handle),
            **kw,
        ),
    )
    provider = SplitwiseClient("id", "secret", "http://127.0.0.1/callback")
    rows, cursor = asyncio.run(
        provider.fetch(
            {"access_token": "token"},
            7,
            "2026-10-25T12:00:00+00:00",
        )
    )
    assert len(rows) == 1
    assert rows[0]["my_share"] == "500"
    assert requests[0].url.params["updated_after"] == "2026-10-25T11:55:00+00:00"
    assert requests[0].url.params["updated_before"] == cursor
    assert requests[1].url.params["offset"] == "1"


def test_provider_failure_is_not_an_empty_success(monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(403)),
            **kw,
        ),
    )
    provider = SplitwiseClient("id", "secret", "http://127.0.0.1/callback")
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(provider.fetch({"access_token": "token"}, 7, None))


def test_groups_only_retain_titles_and_positive_ids(monkeypatch):
    real = httpx.AsyncClient

    def handle(request):
        assert request.url.path.endswith("/get_groups")
        assert request.headers["Authorization"] == "Bearer token"
        return httpx.Response(
            200,
            json={
                "groups": [
                    {"id": 0, "name": "Non-group"},
                    {
                        "id": 9,
                        "name": "Spotify Family",
                        "members": [{"email": "private@example.com"}],
                        "invite_link": "private",
                        "original_debts": [{"amount": "999"}],
                    },
                ]
            },
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handle), **kw)
    )
    provider = SplitwiseClient("id", "secret", "https://example.com/callback")
    assert asyncio.run(provider.groups({"access_token": "token"})) == {"9": "Spotify Family"}
