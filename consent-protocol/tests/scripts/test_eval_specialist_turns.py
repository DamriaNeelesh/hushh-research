"""Offline measurement contracts; fixture-only Nav public path."""

import pytest

from scripts import eval_specialist_turns as harness


def test_fixture_coverage():
    cases = harness.load_cases()
    assert len(cases) == 22
    assert {c["family"] for c in cases} == {
        "active",
        "previous",
        "revoke",
        "details",
        "expiry",
        "explanatory",
        "redirect",
        "out_of_scope",
        "ambiguous",
    }


@pytest.mark.asyncio
async def test_public_path_maps_service_call_and_preserves_directive():
    case = harness.load_cases()[0]
    row = await harness.run_case(case)
    assert row["first_tool_hit"] and row["shape_hit"]
    assert row["directive"]["payload"]["items"][0]["id"] == "one_location_grant:fixture-grant"


@pytest.mark.asyncio
async def test_keyword_miss_stays_miss():
    row = await harness.run_case(harness.load_cases()[1])
    assert row["observed"] == "no_tool"
    assert not row["first_tool_hit"] and not row["shape_hit"]


@pytest.mark.asyncio
async def test_exceptions_are_retained_and_repetitions_all_or_nothing(monkeypatch):
    attempts = iter([True, False])

    async def fake(case):
        ok = next(attempts)
        return {
            "id": case["id"],
            "family": case["family"],
            "first_tool_hit": ok,
            "shape_hit": ok,
            "elapsed_ms": 1,
            "failure": None if ok else "TimeoutError",
        }

    monkeypatch.setattr(harness, "run_case", fake)
    report = await harness.evaluate(harness.load_cases()[:1], runs=2, model="both", mode="baseline")
    assert report["first_tool_rate"] == report["shape_rate"] == 0
    assert report["results"][1]["failure"] == "TimeoutError"
    assert report["model_calls"] == 0 and report["effective_model"] is None
    assert not report["gates"]["passed"]


@pytest.mark.asyncio
async def test_adk_not_fabricated():
    with pytest.raises(ValueError, match="ADK mode unavailable"):
        await harness.evaluate(harness.load_cases(), runs=1, model="gemini-3.8-flash", mode="adk")


def test_shape_rejects_empty_epoch_and_instruction():
    case = {"directive": False}
    assert harness.shape_errors(case, "", None) == ["empty_answer"]
    assert "raw_epoch_or_instruction" in harness.shape_errors(
        case, "You are Nav 1785283200000", None
    )


@pytest.mark.asyncio
async def test_service_failure_is_narrated_without_card():
    case = next(c for c in harness.load_cases() if c["id"] == "unavailable")
    row = await harness.run_case(case)
    assert row["first_tool_hit"] and row["shape_hit"]
    assert "could not load" in row["text"]
    assert row["directive"] is None
