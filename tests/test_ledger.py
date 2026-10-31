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


def test_missing_participant_list_fails_closed(raw):
    raw["users"] = []
    with pytest.raises(ValueError):
        normalize_expense(raw, 99)


def test_duplicate_personal_shares_fail_closed(raw):
    raw["users"].append(raw["users"][0].copy())
    with pytest.raises(ValueError):
        normalize_expense(raw, 7)


@pytest.mark.parametrize("field,value", [("payment", True), ("deleted_at", "2026-10-25")])
def test_settlements_and_deleted_expenses_excluded(raw, field, value):
    raw[field] = value
    assert normalize_expense(raw, 7)["excluded"]


def test_ambiguity_never_defaults_to_misc(raw):
    raw["description"] = "Unclear purchase"
    record = normalize_expense(raw, 7)
    assert classify(record, []) == (None, "needs_review")
    rules = [
        {"description": "unclear purchase", "group_id": 4, "currency": "USD", "category": c}
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
    raw["description"] = "Purchase"
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


def test_group_expenses_between_other_people_are_excluded():
    from splitwise_ledger.domain import normalize_expense

    raw = {
        "id": 100,
        "date": "2026-10-01T00:00:00Z",
        "currency_code": "USD",
        "cost": "50.00",
        "users": [
            {"user_id": 8, "owed_share": "25.00"},
            {"user_id": 9, "owed_share": "25.00"},
        ],
    }
    record = normalize_expense(raw, 7)
    assert record["excluded"] is True
    assert record["my_share"] == "0"


def test_removal_from_expense_excludes_previously_imported_share(tmp_path):
    from splitwise_ledger.domain import normalize_expense
    from splitwise_ledger.store import Store

    raw = {
        "id": 100,
        "date": "2026-10-01T00:00:00Z",
        "currency_code": "USD",
        "cost": "50.00",
        "users": [{"user_id": 7, "owed_share": "50.00"}],
    }
    store = Store(str(tmp_path / "shares.db"))
    store.save_batch([normalize_expense(raw, 7)], "2026-10-01T00:00:00+00:00")
    raw["users"] = [{"user_id": 8, "owed_share": "50.00"}]
    store.save_batch([normalize_expense(raw, 7)], "2026-10-02T00:00:00+00:00")
    rows = store.expenses()
    assert len(rows) == 1
    assert rows[0]["excluded"] is True
    assert rows[0]["my_share"] == "0"


def test_debt_consolidation_is_not_spending_even_when_payment_is_false(raw):
    raw.update(
        description="Settle all balances", payment=False, creation_method="debt_consolidation"
    )
    record = normalize_expense(raw, 7)
    assert record["excluded"] is True
    assert record["my_share"] == "0"
    assert classify(record, []) == (None, "excluded")


def test_repayment_metadata_and_description_do_not_exclude_an_ordinary_purchase(raw):
    raw.update(
        description="Settle all balances",
        creation_method="manual",
        repayments=[{"from": 7, "to": 8, "amount": "25.00"}],
        transaction_confirmed=True,
    )
    assert not normalize_expense(raw, 7)["excluded"]
    assert normalize_expense(raw, 7)["my_share"] == "25.00"


@pytest.mark.parametrize(
    "description,source,expected",
    [
        ("Purchase", "Groceries", Category.GROCERIES),
        ("Purchase", "Dining out", Category.DINING),
        ("Purchase", "Rent", Category.HOME),
        ("Purchase", "Heat/gas", Category.HOME),
        ("Purchase", "Gas/fuel", Category.CAR),
        ("Purchase", "Plane", Category.TRAVEL),
        ("Purchase", "Movies", Category.ENTERTAINMENT),
        ("Purchase", "Sports", Category.SPORTS),
        ("Costco", "General", Category.GROCERIES),
        ("Costco shopping", "General", Category.GROCERIES),
        ("Costco gas", "General", Category.CAR),
        ("Costco", "Gas/fuel", Category.CAR),
        ("Elec bills", "General", Category.HOME),
        ("Elec", "General", Category.HOME),
        ("Elec. bill", "General", Category.HOME),
        ("Electric bills", "General", Category.HOME),
        ("ChatGPT subscription", "General", Category.AI),
        ("Renters insurance", "Insurance", Category.HOME),
        ("Car insurance", "Insurance", Category.CAR),
        ("iCloud subscription", "TV/Phone/Internet", Category.PHONE),
        ("Gym membership", "General", Category.GYM),
        ("Badminton court", "General", Category.SPORTS),
    ],
)
def test_clear_source_and_description_matches(raw, description, source, expected):
    raw.update(description=description, category={"name": source})
    assert classify(normalize_expense(raw, 7), [])[0] == expected


@pytest.mark.parametrize(
    "description,source",
    [
        ("Costco electronics", "General"),
        ("Costco gift", "General"),
        ("Costco groceries and fuel", "General"),
        ("Electronics", "General"),
        ("Amazon", "General"),
        ("Insurance", "Insurance"),
        ("Purchase", "Electronics"),
        ("Purchase", "TV/Phone/Internet"),
        ("Groceries and fuel", "General"),
        ("Dinner", "Groceries"),
        ("Movie gift", "Movies"),
        ("ChatGPT refund", "General"),
    ],
)
def test_ambiguous_or_conflicting_matches_stay_pending(raw, description, source):
    raw.update(description=description, category={"name": source})
    assert classify(normalize_expense(raw, 7), [])[0] is None


def test_rematching_existing_rows_preserves_human_overrides_and_is_idempotent(raw, tmp_path):
    store = Store(str(tmp_path / "rematch.db"))
    record = normalize_expense(raw, 7)
    store.save_batch([record], "first")
    store.review(record["id"], record["revision"], Category.MISC, False)
    assert store.reclassify() == 0
    assert store.expenses()[0]["category"] == Category.MISC
    assert store.expenses()[0]["reason"] == "human"
    # Simulate an import from before automatic category matching was available.
    with store.transaction() as db:
        db.execute("UPDATE expenses SET category=NULL,reason='needs_review'")
    assert store.reclassify() == 1
    assert store.expenses()[0]["category"] == Category.DINING
    assert store.reclassify() == 0


def test_remembering_a_rule_matches_existing_pending_expenses(raw, tmp_path):
    raw["description"] = "Unknown merchant"
    first = normalize_expense(raw, 7)
    raw["id"] += 1
    second = normalize_expense(raw, 7)
    store = Store(str(tmp_path / "remember.db"))
    store.save_batch([first, second], "first")
    store.review(first["id"], first["revision"], Category.LUX, True)
    assert all(row["category"] == Category.LUX for row in store.expenses())
    assert store.expenses()[0]["reason"] == "approved_rule"


def test_settlement_reimport_removes_an_earlier_human_category(raw, tmp_path):
    store = Store(str(tmp_path / "settlement.db"))
    raw.update(description="Settle all balances", payment=False)
    old = normalize_expense(raw, 7)
    store.save_batch([old], "first")
    store.review(old["id"], old["revision"], Category.MISC, False)
    raw["creation_method"] = "debt_consolidation"
    store.save_batch([normalize_expense(raw, 7)], "second")
    assert store.expenses()[0]["excluded"] is True
    assert store.expenses()[0]["category"] is None


def test_personal_rule_overrides_conflicting_automatic_signals(raw):
    raw.update(description="Dinner", category={"name": "Groceries"})
    record = normalize_expense(raw, 7)
    rule = {"description": "dinner", "group_id": 4, "currency": "USD", "category": "Misc"}
    assert classify(record, [rule]) == ("Misc", "approved_rule")
