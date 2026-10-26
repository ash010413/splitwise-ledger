import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from splitwise_ledger.analysis import AnalysisMonth, AnalysisRequest, summarize
from splitwise_ledger.domain import Category


def request():
    return AnalysisRequest(
        current=AnalysisMonth(
            month="2026-10",
            amounts={c: "10.25" for c in Category},
        )
    )


def test_facts_have_exact_total_and_no_transaction_data():
    facts = request().facts()
    assert facts["selected"]["total"] == "123.00"
    assert set(facts["selected"]) == {"month", "category_amounts", "total"}


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1000000001", "bad"])
def test_invalid_amounts_are_rejected(value):
    with pytest.raises(ValidationError):
        AnalysisMonth(month="2026-10", amounts={c: value for c in Category})


def test_all_categories_required():
    with pytest.raises(ValidationError):
        AnalysisMonth(month="2026-10", amounts={Category.HOME: "5"})


def test_all_month_scope_preserves_covered_periods():
    body = AnalysisRequest(
        current=AnalysisMonth(
            month="all",
            covered_months=["2026-10", "2026-09"],
            amounts={c: "1.00" for c in Category},
        )
    )
    facts = body.facts()["selected"]
    assert facts["month"] == "all"
    assert facts["covered_months"] == ["2026-09", "2026-10"]
    assert facts["total"] == "12.00"
    with pytest.raises(ValidationError):
        AnalysisMonth(month="all", amounts={c: "1.00" for c in Category})


def test_gemini_uses_header_secret_and_only_aggregate_payload(monkeypatch):
    def handle(req):
        assert req.headers["x-goog-api-key"] == "private-test-key"
        assert "private-test-key" not in str(req.url)
        body = json.loads(req.content)
        assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
        facts = json.loads(body["contents"][0]["parts"][0]["text"])
        assert facts["selected"]["total"] == "123.00"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": "A short summary."}]},
                    }
                ]
            },
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: client(
            transport=httpx.MockTransport(handle),
            **kw,
        ),
    )
    assert (
        asyncio.run(summarize(request(), "private-test-key", "gemini-3.8-flash"))
        == "A short summary."
    )


def test_blocked_or_incomplete_model_result_is_not_a_summary(monkeypatch):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(
                    200,
                    json={
                        "candidates": [
                            {
                                "finishReason": "MAX_TOKENS",
                                "content": {"parts": [{"text": "Cut off"}]},
                            }
                        ]
                    },
                )
            ),
            **kw,
        ),
    )
    with pytest.raises(ValueError):
        asyncio.run(summarize(request(), "private-test-key", "test-model"))
