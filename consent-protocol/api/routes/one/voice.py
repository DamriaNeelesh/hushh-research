"""One Live Voice routes: readiness, session tickets, and the Live relay.

The retired ``/api/one/adk/*`` voice paths stay as explicit retirement
responders in :mod:`api.routes.one.retired_voice`; this module owns the
maintained surface under ``/api/one/voice``. No provider client is constructed
while ``ONE_VOICE_LIVE_ENABLED`` is off.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

from fastapi import APIRouter, Depends, Request
from google.genai import types as genai_types
from pydantic import BaseModel

from api.middleware import require_firebase_auth
from api.middlewares.rate_limit import RateLimits, limiter
from hushh_mcp.one_voice.config import (
    PROTOCOL_VERSION,
    OneVoiceConfigError,
    OneVoiceLiveConfig,
)
from hushh_mcp.runtime_providers.dependency_health import classify_provider_error
from hushh_mcp.runtime_providers.factory import build_managed_live_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/one/voice", tags=["One voice"])

_READINESS_PROBE_TIMEOUT_SECONDS = 8.0
_READINESS_TTL_SECONDS = 60.0

ReadinessStatus = Literal["ready", "disabled", "not_configured", "provider_unavailable"]


class VoiceReadinessResponse(BaseModel):
    """The single flag the frontend reads to decide which voice owner mounts."""

    enabled: bool
    status: ReadinessStatus
    model: str | None = None
    location: str | None = None
    protocol_version: Literal["one-voice-v1"] = PROTOCOL_VERSION
    ws_path: str = "/api/one/voice/live"


_readiness_cache: tuple[float, VoiceReadinessResponse] | None = None


def reset_readiness_cache() -> None:
    global _readiness_cache
    _readiness_cache = None


async def _probe_live_connect(config: OneVoiceLiveConfig) -> None:
    """Open and immediately close one Live session. No audio, no output."""
    client = build_managed_live_client(model=config.model_id, location=config.location)
    live_config = genai_types.LiveConnectConfig(response_modalities=[genai_types.Modality.TEXT])
    async with client.aio.live.connect(model=config.model_id, config=live_config):
        return


async def compute_readiness() -> VoiceReadinessResponse:
    """Evaluate the flag, the contract, and (when enabled) a cached connect probe."""
    global _readiness_cache
    now = time.monotonic()
    if _readiness_cache and now - _readiness_cache[0] <= _READINESS_TTL_SECONDS:
        return _readiness_cache[1]
    try:
        config = OneVoiceLiveConfig.from_environment()
    except OneVoiceConfigError:
        logger.warning("one_voice.readiness reason=not_configured")
        response = VoiceReadinessResponse(enabled=False, status="not_configured")
        _readiness_cache = (now, response)
        return response
    if not config.enabled:
        # Not cached: turning the flag on must take effect on the next request.
        return VoiceReadinessResponse(enabled=False, status="disabled")
    try:
        await asyncio.wait_for(
            _probe_live_connect(config), timeout=_READINESS_PROBE_TIMEOUT_SECONDS
        )
    except Exception as exc:  # noqa: BLE001 - classified, never reflected
        logger.warning(
            "one_voice.readiness reason=provider_unavailable class=%s",
            classify_provider_error(exc),
        )
        response = VoiceReadinessResponse(
            enabled=False,
            status="provider_unavailable",
            model=config.model_id,
            location=config.location,
        )
        _readiness_cache = (now, response)
        return response
    response = VoiceReadinessResponse(
        enabled=True,
        status="ready",
        model=config.model_id,
        location=config.location,
    )
    _readiness_cache = (now, response)
    return response


@router.get("/readiness", response_model=VoiceReadinessResponse)
@limiter.limit(RateLimits.AGENT_CHAT)
async def voice_readiness(
    request: Request,
    _firebase_uid: str = Depends(require_firebase_auth),
) -> VoiceReadinessResponse:
    """Cached, output-suppressed proof that a Live session can be opened.

    Always HTTP 200: the frontend decides what to mount from ``enabled``. A
    provider outage reports ``provider_unavailable`` and hides the control; it
    never falls back to another model or region.
    """
    return await compute_readiness()
