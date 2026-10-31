import copy
import time

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from firestore_fake import Client
from google.cloud import firestore

from splitwise_ledger.domain import Category, normalize_expense
from splitwise_ledger.firestore_accounts import FirestoreAccounts
from splitwise_ledger.firestore_ledger import (
    _CACHE,
    _CACHE_LOCK,
    CURRENT_OPERATION,
    FirestoreLedger,
)
from splitwise_ledger.mobile import Handoff
from splitwise_ledger.store import ConflictError


@pytest.fixture
def cloud_client(monkeypatch):
    monkeypatch.setattr(firestore, "transactional", lambda fn: lambda tx: tx.run(fn))
    return Client()


def purchase(i=1, description="Unknown purpose"):
    return normalize_expense(
        {
            "id": i,
            "description": description,
            "date": "2026-10-01T00:00:00Z",
            "currency_code": "USD",
            "cost": "15.00",
            "users": [{"user_id": 7, "owed_share": "10.00"}],
        },
        7,
    )


def test_cloud_ledger_atomic_edits_cold_start_and_account_isolation(cloud_client):
    ledger = FirestoreLedger(cloud_client, 7)
    ledger.save_batch([purchase()], "initial", synced_at=1)
    original = ledger.expenses()[0]
    ledger.review(1, original["revision"], Category.LUX, True)
    with _CACHE_LOCK:
        _CACHE.clear()
    restarted = FirestoreLedger(cloud_client, 7)
    assert restarted.expenses()[0]["category"] == "Lux"
    assert FirestoreLedger(cloud_client, 8).expenses() == []
    assert restarted.get("last_successful_sync_at") == 1
    before = copy.deepcopy(cloud_client.data)
    with pytest.raises(ConflictError):
        restarted.review(1, "stale-revision", Category.HOME, True)
    assert cloud_client.data == before
    restarted.save_batch([purchase(description="Changed unknown purpose")], "later")
    assert restarted.expenses()[0]["reason"] == "source_changed"
    assert restarted.expenses()[0]["category"] is None
    assert restarted.get("sync_cursor") == "later"


def test_paging_cache_and_import_capacity_failure_keep_previous_cursor(cloud_client):
    ledger = FirestoreLedger(cloud_client, 7)
    ledger.save_batch([purchase(i) for i in range(500)], "initial")
    assert len(cloud_client.data["minto_ledgers/7"]["pages"]) == 64
    assert len(ledger.expenses()) == 500
    assert cloud_client.reads == 0  # Own committed pages are already cached.
    with _CACHE_LOCK:
        _CACHE.clear()
    assert len(ledger.expenses()) == 500
    assert cloud_client.reads == 64
    ledger.expenses()
    assert cloud_client.reads == 64
    before = copy.deepcopy(cloud_client.data)
    record = purchase(999)
    record["details"] = "x" * 900_000
    with pytest.raises(ValueError):
        ledger.save_batch([record], "must-not-advance")
    assert cloud_client.data == before
    assert ledger.get("sync_cursor") == "initial"


def test_stale_worker_lease_cannot_commit(cloud_client):
    ledger = FirestoreLedger(cloud_client, 7)
    ledger.save_batch([purchase()], "initial")
    cloud_client.data["minto_leases/7"] = {"owner": "new-worker", "expires": time.time() + 100}
    handle = CURRENT_OPERATION.set((7, "old-worker"))
    try:
        with pytest.raises(HTTPException) as error:
            ledger.save_batch([purchase(2)], "stale-cursor")
        assert error.value.status_code == 409
        assert ledger.get("sync_cursor") == "initial"
        assert len(ledger.expenses()) == 1
    finally:
        CURRENT_OPERATION.reset(handle)


def test_auth_handoff_is_single_use_and_tokens_are_encrypted(cloud_client):
    accounts = FirestoreAccounts(cloud_client, Fernet(Fernet.generate_key()), max_accounts=1)
    body = Handoff(state="minto_" + "s" * 40, verifier="v" * 40)
    accounts.start_login(body.state, body.verifier)
    with pytest.raises(HTTPException):
        accounts.claim_login(body.state, "wrong-cookie")
    accounts.claim_login(body.state, body.state)
    with pytest.raises(HTTPException):
        accounts.claim_login(body.state, body.state)
    accounts.complete_login(body.state, 7, {"access_token": "provider-secret"})
    assert "provider-secret" not in str(cloud_client.data)
    assert accounts.exchange_login(body, "native-session") == 7
    assert accounts.user("native-session") == 7
    assert "native-session" not in str(cloud_client.data)
    with pytest.raises(HTTPException):
        accounts.exchange_login(body, "replayed")
    accounts.logout("native-session")
    with pytest.raises(HTTPException):
        accounts.user("native-session")
    accounts.start_login("second", "verifier")
    accounts.claim_login("second", "second")
    with pytest.raises(HTTPException) as error:
        accounts.complete_login("second", 8, {"access_token": "other"})
    assert error.value.status_code == 403
    assert accounts.users() == [7]


def test_hosted_api_uses_durable_accounts_and_disables_legacy_routes(cloud_client, tmp_path):
    from unittest.mock import patch

    from fastapi.testclient import TestClient
    from test_mobile import Provider, login

    from splitwise_ledger.api import Settings, create_app

    settings = Settings(
        _env_file=None,
        app_api_token="x" * 32,
        token_encryption_key=Fernet.generate_key().decode(),
        storage_backend="firestore",
        firestore_project="test",
        daily_sync_enabled=False,
        splitwise_client_id="test",
        splitwise_client_secret="secret",
        scheduler_audience="https://test.run.app",
        scheduler_service_account="sync@test.iam.gserviceaccount.com",
    )
    with patch.object(firestore, "Client", return_value=cloud_client):
        with TestClient(create_app(settings, Provider())) as client:
            headers = login(client)
            assert client.post("/mobile/sync", headers=headers).status_code == 200
            row = client.get("/mobile/expenses", headers=headers).json()["expenses"][0]
            assert row["my_share"] == "30.00"
            assert (
                client.post(
                    "/mobile/expenses/42/review",
                    headers=headers,
                    json={"revision": row["revision"], "category": "Lux"},
                ).status_code
                == 200
            )
            assert client.get("/expenses", headers=headers).status_code == 404
            assert client.post("/internal/sync").status_code == 401
            assert client.get("/oauth/splitwise/callback").status_code == 400
            with patch(
                "google.oauth2.id_token.verify_oauth2_token",
                return_value={"email": "attacker@example.com", "email_verified": True},
            ):
                assert (
                    client.post(
                        "/internal/sync", headers={"Authorization": "Bearer forged"}
                    ).status_code
                    == 403
                )
            with patch(
                "google.oauth2.id_token.verify_oauth2_token",
                return_value={"email": settings.scheduler_service_account, "email_verified": True},
            ):
                assert (
                    client.post(
                        "/internal/sync", headers={"Authorization": "Bearer test"}
                    ).status_code
                    == 200
                )
        with TestClient(create_app(settings, Provider())) as restarted:
            assert (
                restarted.get("/mobile/expenses", headers=headers).json()["expenses"][0]["category"]
                == "Lux"
            )


def test_cloud_run_fails_closed_with_local_storage(monkeypatch):
    from splitwise_ledger.api import Settings, create_app

    monkeypatch.setenv("K_SERVICE", "test")
    settings = Settings(
        _env_file=None, app_api_token="x" * 32, token_encryption_key=Fernet.generate_key().decode()
    )
    with pytest.raises(ValueError, match="Cloud Run requires Firestore"):
        create_app(settings)


def test_sqlite_migration_preserves_categories_and_never_overwrites_cloud_edits(
    cloud_client, tmp_path
):
    import importlib.util
    from pathlib import Path

    from splitwise_ledger.store import Store

    path = Path(__file__).resolve().parents[1] / "tools" / "migrate_to_firestore.py"
    spec = importlib.util.spec_from_file_location("migration_tool", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    source = Store(str(tmp_path / "source.sqlite3"))
    source.save_batch([purchase(), purchase(2)], "source-cursor", synced_at=123)
    source.begin_history()
    source.review(1, source.expenses()[1]["revision"], Category.HOME, True)
    cloud = FirestoreLedger(cloud_client, 7)
    assert migration.import_ledger(source, cloud) is True
    assert cloud.expenses() == source.expenses()
    assert cloud.get("last_successful_sync_at") == 123
    assert cloud.historical_ids() == source.historical_ids()
    cloud.review(2, cloud.expenses()[0]["revision"], Category.LUX, False)
    assert migration.import_ledger(source, cloud) is False
    assert cloud.expenses()[0]["category"] == "Lux"


def test_hosted_expense_responses_are_compressed_without_changing_shares(cloud_client):
    from unittest.mock import patch

    from fastapi.testclient import TestClient
    from test_mobile import Provider

    from splitwise_ledger.api import Settings, create_app
    from splitwise_ledger.mobile import digest

    FirestoreLedger(cloud_client, 7).save_batch([purchase(i) for i in range(100)], "cursor")
    cloud_client.data["minto_sessions/" + digest("session")] = {
        "user_id": 7,
        "expires": time.time() + 100,
    }
    settings = Settings(
        _env_file=None,
        app_api_token="x" * 32,
        token_encryption_key=Fernet.generate_key().decode(),
        storage_backend="firestore",
        firestore_project="test",
        daily_sync_enabled=False,
    )
    with (
        patch.object(firestore, "Client", return_value=cloud_client),
        TestClient(create_app(settings, Provider())) as client,
    ):
        response = client.get(
            "/mobile/expenses",
            headers={"Authorization": "Bearer session", "Accept-Encoding": "gzip"},
        )
        assert response.status_code == 200
        assert response.headers["content-encoding"] == "gzip"
        rows = response.json()["expenses"]
        assert len(rows) == 100
        assert all(row["my_share"] == "10.00" for row in rows)
