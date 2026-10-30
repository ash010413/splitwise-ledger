import asyncio
import copy
import json

import httpx
import pytest

from splitwise_ledger.categorization import POLICY_VERSION, Decision, categorize_pending
from splitwise_ledger.domain import Category, normalize_expense
from splitwise_ledger.store import Store


@pytest.fixture
def store(tmp_path):
    store = Store(str(tmp_path / "categories.db"))
    rows = [
        normalize_expense(
            {
                "id": i,
                "description": description,
                "date": "2026-10-01T00:00:00Z",
                "currency_code": "USD",
                "cost": "15.00",
                "group_id": 2,
                "users": [{"user_id": 7, "owed_share": "10.00"}],
                "category": {"name": "General"},
            },
            7,
        )
        for i, description in [(1, "Trader Joe’s"), (2, "Unclear initials QZ")]
    ]
    store.save_batch(rows, "cursor")
    return store


def mock_model(monkeypatch, response, inspect=None):
    real = httpx.AsyncClient

    def handle(request):
        if inspect:
            inspect(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": json.dumps(response)}]},
                    }
                ]
            },
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handle), **kw)
    )


def test_matching_uses_minimal_context_and_does_not_repeat_uncertain_items(store, monkeypatch):
    calls = []

    def inspect(req):
        assert req.headers["x-goog-api-key"] == "test-secret"
        body = json.loads(req.content)
        items = json.loads(body["contents"][0]["parts"][0]["text"])
        assert set(items[0]) == {"item", "description", "source_category"}
        assert "Misc" in body["systemInstruction"]["parts"][0]["text"]
        calls.append(1)

    # Store returns the most recent ID first: QZ, then Trader Joe's.
    response = {
        "decisions": [
            {"item": 0, "category": None, "certain": False, "reason": "Unknown initials."},
            {"item": 1, "category": "Groceries", "certain": True, "reason": "Grocery store."},
        ]
    }
    mock_model(monkeypatch, response, inspect)
    result = asyncio.run(categorize_pending(store, "test-secret", "test-model"))
    assert result == {"matched": 1, "review": 1, "remaining": 0}
    assert store.expenses()[0]["category"] is None
    assert store.expenses()[1]["category"] == Category.GROCERIES
    assert store.expenses()[1]["reason"] == "gemini"
    assert store.reclassify() == 0  # A normal sync must not erase Gemini decisions.
    assert asyncio.run(categorize_pending(store, "test-secret", "test-model"))["matched"] == 0
    assert len(calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        {"decisions": [{"item": 0, "category": "Groceries", "certain": True, "reason": "Food."}]},
        {
            "decisions": [
                {"item": 0, "category": "Groceries", "certain": True, "reason": "Food."},
                {"item": 0, "category": "Groceries", "certain": True, "reason": "Food."},
            ]
        },
        {"decisions": [{"item": 0, "category": "Invented", "certain": True, "reason": "Unknown."}]},
    ],
)
def test_invalid_or_partial_batches_do_not_change_categories(store, monkeypatch, response):
    before = copy.deepcopy(store.expenses())
    mock_model(monkeypatch, response)
    with pytest.raises(ValueError):
        asyncio.run(categorize_pending(store, "test-secret", "test-model"))
    assert store.expenses() == before
    assert len(store.ai_pending(POLICY_VERSION)) == 2


def test_inflight_human_choice_and_source_edit_win_over_ai(store):
    groups = store.ai_pending(POLICY_VERSION)
    store.review(2, groups[0][0]["revision"], Category.LUX, False)
    changed = dict(groups[1][0], revision="source-changed")
    store.save_batch([changed], "new-cursor")
    decisions = [
        Decision(item=i, category=Category.GROCERIES, certain=True, reason="Food.")
        for i in range(2)
    ]
    assert store.apply_ai_decisions(groups, decisions, POLICY_VERSION, "test-model") == (0, 0)
    assert store.expenses()[0]["category"] == Category.LUX
    assert store.expenses()[1]["category"] is None


def test_uncertain_category_is_never_silently_applied(store):
    groups = store.ai_pending(POLICY_VERSION)
    decisions = [
        Decision(item=i, category=Category.MISC, certain=False, reason="Not enough context.")
        for i in range(2)
    ]
    assert store.apply_ai_decisions(groups, decisions, POLICY_VERSION, "test-model") == (0, 2)
    assert all(row["category"] is None for row in store.expenses())


def test_historical_fallback_waits_for_gemini_and_new_backdated_expenses_still_need_review(
    store, monkeypatch
):
    store.begin_history()
    assert store.finish_history(POLICY_VERSION) == 0
    assert all(r["category"] is None for r in store.expenses())
    mock_model(
        monkeypatch,
        {
            "decisions": [
                {
                    "item": 0,
                    "category": "Needs review",
                    "certain": False,
                    "reason": "Unknown initials",
                },
                {"item": 1, "category": "Groceries", "certain": True, "reason": "Grocery merchant"},
            ]
        },
    )
    asyncio.run(categorize_pending(store, "test", "test"))
    assert store.finish_history(POLICY_VERSION) == 1
    rows = store.expenses()
    assert rows[0]["category"] == Category.OTHERS
    assert rows[1]["category"] == Category.GROCERIES
    assert store.reclassify() == 0
    new = dict(rows[0], id=99, revision="new-import", date="2020-01-01T00:00:00Z")
    store.save_batch([new], "later")
    store.begin_history()
    groups = store.ai_pending(POLICY_VERSION)
    assert [r["id"] for g in groups for r in g] == [99]
    store.apply_ai_decisions(
        groups,
        [Decision(item=0, category=None, certain=False, reason="Unclear")],
        POLICY_VERSION,
        "test",
    )
    store.finish_history(POLICY_VERSION)
    assert store.expenses()[0]["category"] is None
    assert 99 not in store.historical_ids()
    store.review(2, rows[0]["revision"], Category.LUX, False)
    assert store.finish_history(POLICY_VERSION) == 0
    assert store.expenses()[1]["category"] == Category.LUX


def test_history_freezes_after_initial_complete_fetch_even_if_empty(tmp_path):
    store = Store(str(tmp_path / "empty.db"))
    store.begin_history()
    assert store.get("history_initialized") is None
    store.save_batch([], "cursor")
    store.begin_history()
    assert store.get("history_initialized") is True
    assert store.historical_ids() == set()


def test_edited_historical_fallback_gets_a_fresh_gemini_attempt(store):
    store.begin_history()
    groups = store.ai_pending(POLICY_VERSION)
    store.apply_ai_decisions(
        groups,
        [Decision(item=i, category=None, certain=False, reason="Unknown") for i in range(2)],
        POLICY_VERSION,
        "test",
    )
    assert store.finish_history(POLICY_VERSION) == 2
    changed = dict(
        store.expenses()[0], revision="edited-description", description="Trader Joe’s snacks"
    )
    store.save_batch([changed], "later")
    assert store.expenses()[0]["category"] is None
    assert store.finish_history(POLICY_VERSION) == 0
    pending = store.ai_pending(POLICY_VERSION)
    assert len(pending) == 1
    store.apply_ai_decisions(
        pending,
        [Decision(item=0, category=Category.GROCERIES, certain=True, reason="Grocery purchase")],
        POLICY_VERSION,
        "test",
    )
    assert store.expenses()[0]["category"] == Category.GROCERIES
