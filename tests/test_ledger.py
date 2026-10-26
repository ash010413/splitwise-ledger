import copy

import pytest

from splitwise_ledger.domain import Category, classify, normalize_expense
from splitwise_ledger.store import ConflictError, Store


@pytest.fixture
def raw():
    return {
        "id": 123,
        "description": "Dinner",
        "details": "",
        "date": "2026-10-25T12:00:00Z",
        "currency_code": "USD",
        "cost": "100.00",
        "group_id": 4,
        "payment": False,
        "users": [
            {"user_id": 7, "owed_share": "25.00", "paid_share": "100.00", "net_balance": "75.00"}
        ],
    }


def test_uses_consumption_not_cash_paid_or_net_balance(raw):
    assert normalize_expense(raw, 7)["my_share"] == "25.00"
    raw["users"][0]["paid_share"] = "0"
    raw["users"][0]["net_balance"] = "-25.00"
    assert normalize_expense(raw, 7)["my_share"] == "25.00"


def test_missing_share_fails_closed(raw):
    with pytest.raises(ValueError):
        normalize_expense(raw, 99)


@pytest.mark.parametrize("field,value", [("payment", True), ("deleted_at", "2026-10-25")])
def test_settlements_and_deleted_expenses_excluded(raw, field, value):
    raw[field] = value
    assert normalize_expense(raw, 7)["excluded"]


def test_ambiguity_never_defaults_to_misc(raw):
    record = normalize_expense(raw, 7)
    assert classify(record, []) == (None, "needs_review")
    rules = [
        {"description": "dinner", "group_id": 4, "currency": "USD", "category": c}
        for c in ["Food / Dining", "Misc"]
    ]
    assert classify(record, rules) == (None, "conflicting_rules")


def test_sync_idempotence_and_material_edit_reopens_review(raw, tmp_path):
    store = Store(str(tmp_path / "ledger.db"))
    record = normalize_expense(raw, 7)
    store.save_batch([record], "2026-10-25T00:00:00+00:00")
    store.review(123, record["revision"], Category.DINING, True)
    store.save_batch([record], "2026-10-26T00:00:00+00:00")
    assert len(store.expenses()) == 1
    assert store.expenses()[0]["reason"] == "human"
    changed = copy.deepcopy(raw)
    changed["users"][0]["owed_share"] = "30.00"
    store.save_batch([normalize_expense(changed, 7)], "2026-10-27T00:00:00+00:00")
    assert store.expenses()[0]["category"] is None
    assert store.expenses()[0]["reason"] == "source_changed"
    with pytest.raises(ConflictError):
        store.review(123, record["revision"], Category.DINING, False)


def test_remembered_rules_have_group_and_currency_scope(raw, tmp_path):
    store = Store(str(tmp_path / "ledger.db"))
    record = normalize_expense(raw, 7)
    store.save_batch([record], "first")
    store.review(123, record["revision"], Category.DINING, True)
    raw["id"] = 124
    store.save_batch([normalize_expense(raw, 7)], "second")
    assert store.expenses()[0]["reason"] == "approved_rule"
    raw["id"], raw["group_id"] = 125, 99
    store.save_batch([normalize_expense(raw, 7)], "third")
    assert store.expenses()[0]["category"] is None


def test_batch_rollback_preserves_cursor(raw, tmp_path):
    store = Store(str(tmp_path / "ledger.db"))
    record = normalize_expense(raw, 7)
    store.save_batch([record], "first")
    invalid = dict(record, id=124)
    del invalid["revision"]
    with pytest.raises(KeyError):
        store.save_batch([dict(record, id=125), invalid], "second")
    assert store.get("sync_cursor") == "first"
    assert len(store.expenses()) == 1
