#!/usr/bin/env python3
"""Fixture-backed public Nav turn measurement, without production information.

Baseline mode executes NavAgent.handle with fixture admission and service results.
It performs no model calls: requested model labels are comparison metadata only.
ADK mode intentionally fails closed until the migrated public path is instrumented.
The shim's service calls are mapped to equivalent leaf-tool names, not represented
as actual model tool calls. Failures remain in the denominator and raw report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_CASES = ROOT / "scripts/eval_cases/nav_specialist_turns.v1.json"
SCHEMA_VERSION = "nav.specialist_turns.v1"
MODELS = ("gemini-3.8-flash", "gemini-3.7-flash")


def load_cases(path: Path = DEFAULT_CASES) -> list[dict]:
    payload = json.loads(path.read_text())
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported schema_version")
    cases = payload["cases"]
    ids = [case["id"] for case in cases]
    if not cases or len(ids) != len(set(ids)):
        raise ValueError("Cases must be nonempty with unique ids")
    for case in cases:
        if not case.get("prompt") or not case.get("family") or not case.get("expected"):
            raise ValueError("Missing case prompt, family or expected first tool")
        if case.get("fixture", "normal") not in {"normal", "empty", "unavailable"}:
            raise ValueError("Unknown service fixture")
    return cases


def percentile(values: list[float], fraction: float) -> float | None:
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def shape_errors(case: dict, text: str, directive: dict | None) -> list[str]:
    errors = []
    if not text.strip():
        errors.append("empty_answer")
    if re.search(r"\b\d{13}\b", text) or "you are nav" in text.lower():
        errors.append("raw_epoch_or_instruction")
    if case.get("directive"):
        items = (directive or {}).get("payload", {}).get("items", [])
        if not any(
            item.get("id") == "one_location_grant:fixture-grant"
            and item.get("actions") == ["revoke", "details"]
            for item in items
        ):
            errors.append("missing_revocable_grant_card")
    elif directive is not None:
        errors.append("unexpected_directive")
    for word in case.get("contains", []):
        if word.lower() not in text.lower():
            errors.append(f"missing_fixture_content:{word}")
    return errors


async def run_case(case: dict) -> dict:
    from dataclasses import asdict

    from hushh_mcp.adk_bridge import nav_agent
    from hushh_mcp.adk_bridge.contract import A2ATask

    # Do not let a later migration silently turn an offline baseline into cloud calls.
    if not callable(getattr(nav_agent.NavAgent, "_answer", None)) or not callable(
        getattr(nav_agent, "_is_active_consent_query", None)
    ):
        raise ValueError("Keyword shim unavailable; baseline requires its original revision")
    calls: list[str] = []
    service_errors: list[str] = []

    async def admitted(*args, **kwargs):
        return SimpleNamespace(ok=True)

    async def list_center(self, user_id, **kwargs):
        if user_id != "nav_eval_fixture":
            raise AssertionError("Non-fixture owner rejected")
        surface = kwargs["surface"]
        if surface not in {"active", "previous"}:
            raise AssertionError("Unexpected consent surface")
        calls.append(f"list_{'active' if surface == 'active' else 'previous'}_consent_grants")
        if case.get("fixture") == "unavailable":
            service_errors.append("fixture_service_unavailable")
            raise RuntimeError("fixture service unavailable")
        if case.get("fixture") == "empty":
            return {"items": [], "total": 0}
        return {
            "total": 1,
            "items": [
                {
                    "id": "one_location_grant:fixture-grant",
                    "counterpart_label": "Alex",
                    "scope": "cap.location.live.view",
                    "expires_at": "1785283200000",
                    "status": "active" if surface == "active" else "revoked",
                    "revoked_at": "2026-07-28T00:00:00Z" if surface == "previous" else None,
                    "metadata": {"grant_id": "fixture-grant"},
                }
            ],
        }

    started = time.perf_counter()
    text, directive, failure = "", None, None
    try:
        with (
            patch.object(nav_agent, "validate_a2a_consent_token_with_db", admitted),
            patch.object(nav_agent.ConsentCenterService, "list_center", list_center),
        ):
            result = await asyncio.wait_for(
                nav_agent.NavAgent().handle(
                    A2ATask(
                        user_id="nav_eval_fixture",
                        consent_token="fixture-only-not-a-token",
                        conversation_id="nav_eval",
                        message=case["prompt"],
                        timezone="UTC",
                    )
                ),
                timeout=60,
            )
            text = result.text
            directive = asdict(result.directive) if result.directive else None
    except Exception as exc:
        # Fixture-only execution: retain the failure class without arbitrary exception text.
        failure = type(exc).__name__
    elapsed_ms = (time.perf_counter() - started) * 1000
    observed = calls[0] if calls else "no_tool"
    errors = shape_errors(case, text, directive)
    return {
        "id": case["id"],
        "family": case["family"],
        "observed": observed,
        "service_trajectory": calls,
        "service_errors": service_errors,
        "first_tool_hit": failure is None and observed in case["expected"],
        "shape_hit": failure is None and not errors,
        "shape_errors": errors,
        "failure": failure,
        "elapsed_ms": elapsed_ms,
        "text": text,
        "directive": directive,
    }


async def evaluate(
    cases: list[dict],
    *,
    runs: int,
    model: str,
    mode: str,
    min_first_tool_rate: float = 0.9,
    min_shape_rate: float = 0.9,
    max_p95_latency_ms: float = 8000,
) -> dict:
    if mode != "baseline":
        raise ValueError("ADK mode unavailable: migrate and instrument Nav before measuring it")
    if runs < 1:
        raise ValueError("runs must be positive")
    rows = []
    for case in cases:
        for rep in range(runs):
            rows.append({**await run_case(case), "rep": rep + 1})

    def rate(key):
        return sum(
            all(row[key] for row in rows if row["id"] == case["id"]) for case in cases
        ) / len(cases)

    first, shape = rate("first_tool_hit"), rate("shape_hit")
    latencies = [row["elapsed_ms"] for row in rows]
    p95 = percentile(latencies, 0.95)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    )
    breaches = []
    if first < min_first_tool_rate:
        breaches.append("first_tool_rate")
    if shape < min_shape_rate:
        breaches.append("shape_rate")
    if percentile(latencies, 0.5) > 4000:
        breaches.append("p50_latency")
    if p95 > max_p95_latency_ms:
        breaches.append("p95_latency")
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "commit": commit,
        "dirty": dirty,
        "specialist": "nav",
        "mode": mode,
        "requested_model": model,
        "effective_model": None,
        "model_calls": 0,
        "measurement": "fixture-backed keyword-shim service calls; not model tool calls or live service latency",
        "runs": runs,
        "cases": len(cases),
        "first_tool_rate": first,
        "shape_rate": shape,
        "latency_ms": {"p50": percentile(latencies, 0.5), "p95": p95, "max": max(latencies)},
        "gates": {
            "passed": not breaches,
            "breaches": breaches,
            "min_first_tool_rate": min_first_tool_rate,
            "min_shape_rate": min_shape_rate,
            "max_p50_latency_ms": 4000,
            "max_p95_latency_ms": max_p95_latency_ms,
        },
        "results": rows,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--specialist", choices=["nav"], default="nav")
    parser.add_argument("--mode", choices=["baseline", "adk"], default="baseline")
    parser.add_argument("--model", choices=[*MODELS, "both"], default="both")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--report", type=Path, default=ROOT / "artifacts/specialist_turns_eval_latest.json"
    )
    parser.add_argument("--min-first-tool-rate", type=float, default=0.9)
    parser.add_argument("--min-shape-rate", type=float, default=0.9)
    parser.add_argument("--max-p95-latency-ms", type=float, default=8000)
    args = parser.parse_args(argv)
    if args.mode != "baseline" or args.runs < 1:
        parser.error("Only fixture baseline mode is implemented; runs must be positive")
    if (
        not all(0 <= x <= 1 for x in (args.min_first_tool_rate, args.min_shape_rate))
        or args.max_p95_latency_ms <= 0
    ):
        parser.error("Rates must be between 0 and 1; latency budget must be positive")
    report = asyncio.run(
        evaluate(
            load_cases(args.cases),
            runs=args.runs,
            model=args.model,
            mode=args.mode,
            min_first_tool_rate=args.min_first_tool_rate,
            min_shape_rate=args.min_shape_rate,
            max_p95_latency_ms=args.max_p95_latency_ms,
        )
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("first_tool_rate", "shape_rate", "gates")}))
    return 0 if report["gates"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
