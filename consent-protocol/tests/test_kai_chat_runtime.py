"""Focused tests for Kai's manifest-owned chat runtime."""

from __future__ import annotations

import pytest

from hushh_mcp.agents.kai import runtime


def test_chat_gene_loads_from_kai_manifest() -> None:
    gene = runtime.load_kai_chat_gene()

    assert gene.id == "agent_kai_chat"
    assert gene.runtime.adk_mode == "chat"
    assert gene.runtime.transport == ["chat", "in_process"]
    assert gene.privacy.plaintext_telemetry is False


@pytest.mark.asyncio
async def test_chat_runtime_uses_one_bounded_adk_turn(monkeypatch) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        runtime,
        "build_kai_chat_agent",
        lambda **kwargs: calls.setdefault("agent", kwargs) or "agent",
    )

    class _Turn:
        final_text = "Kai response with grounded context."

    async def _run_turn(**kwargs):
        calls["kwargs"] = kwargs
        return _Turn()

    monkeypatch.setattr(runtime, "run_specialist_adk_turn", _run_turn)

    response = await runtime.run_kai_chat_turn(
        system_instruction="Use only supplied context.",
        user_message="What should I review?",
        user_id="user-1",
        consent_token="owner-token",  # noqa: S106 - test fixture token
        timeout_seconds=45,
    )

    assert response == "Kai response with grounded context."
    assert calls["kwargs"]["app_name"] == "hushh_kai_chat"
    assert calls["kwargs"]["user_id"] == "user-1"
    assert calls["kwargs"]["consent_token"] == "owner-token"
    assert calls["kwargs"]["message"] == "What should I review?"
    assert calls["kwargs"]["max_llm_calls"] == 1
    assert calls["kwargs"]["total_timeout_s"] == 45


@pytest.mark.asyncio
async def test_chat_runtime_requires_authority_and_nonempty_input() -> None:
    with pytest.raises(ValueError, match="instruction and message"):
        await runtime.run_kai_chat_turn(
            system_instruction="",
            user_message="hello",
            user_id="user-1",
            consent_token="token",  # noqa: S106 - test fixture token
        )
    with pytest.raises(ValueError, match="authority"):
        await runtime.run_kai_chat_turn(
            system_instruction="system",
            user_message="hello",
            user_id="",
            consent_token="token",  # noqa: S106 - test fixture token
        )
