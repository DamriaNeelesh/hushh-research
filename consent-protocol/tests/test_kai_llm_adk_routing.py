"""Contract tests that Kai analyst operons use manifest-owned ADK turns."""

from __future__ import annotations

import pytest

from hushh_mcp.operons.kai import llm


@pytest.fixture(autouse=True)
def valid_consent(monkeypatch):
    monkeypatch.setattr(llm, "validate_token", lambda *_args, **_kwargs: (True, "", None))


@pytest.mark.asyncio
async def test_fundamental_operon_routes_to_manifest_gene(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    async def _run(**kwargs):
        calls.append(kwargs)
        return {
            "summary": "grounded",
            "business_moat": "durable",
            "financial_resilience": "sound",
            "growth_efficiency": "measured",
            "bull_case": "upside",
            "bear_case": "risk",
            "confidence": 0.8,
            "recommendation": "hold",
        }

    monkeypatch.setattr(llm, "run_kai_analyst_turn", _run)

    result = await llm.analyze_stock_with_gemini(
        ticker="AAPL",
        user_id="user-1",
        consent_token="token",  # noqa: S106 - test fixture token
        sec_data={"entity_name": "Apple", "latest_10k": {}},
        market_data={"price": 100},
        quant_metrics={},
    )

    assert result["recommendation"] == "hold"
    assert calls[0]["gene_id"] == "agent_kai_fundamental"
    assert calls[0]["user_id"] == "user-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("function_name", "gene_id", "kwargs"),
    [
        (
            "analyze_sentiment_with_gemini",
            "agent_kai_sentiment",
            {"news_articles": [], "market_data": {}},
        ),
        (
            "analyze_valuation_with_gemini",
            "agent_kai_valuation",
            {"market_data": {}, "peer_data": []},
        ),
    ],
)
async def test_other_analyst_operons_route_to_manifest_genes(
    monkeypatch, function_name: str, gene_id: str, kwargs: dict[str, object]
) -> None:
    calls: list[dict[str, object]] = []

    async def _run(**call_kwargs):
        calls.append(call_kwargs)
        return {
            "summary": "grounded",
            "sentiment_score": 0.0,
            "key_catalysts": [],
            "news_highlights": [],
            "momentum_signal": "neutral",
            "valuation_verdict": "fair",
            "valuation_metrics": {},
            "peer_ranking": "middle",
            "price_targets": {},
            "upside_downside": {},
            "confidence": 0.5,
            "recommendation": "neutral" if "sentiment" in gene_id else "fair",
        }

    monkeypatch.setattr(llm, "run_kai_analyst_turn", _run)
    function = getattr(llm, function_name)
    result = await function(
        ticker="AAPL",
        user_id="user-1",
        consent_token="token",  # noqa: S106 - test fixture token
        **kwargs,
    )

    assert result["summary"] == "grounded"
    assert calls[0]["gene_id"] == gene_id
