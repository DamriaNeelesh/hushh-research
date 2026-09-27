"""One's turn-scoped location and weather (hushh_mcp/one_adk/turn_location.py).

Location is level-4 personal information. The contract: the device supplies a
coarse position only for the turn that asks; the server keeps it in memory
behind an opaque reference, never in state, forwarded props or logs; without it
the tools say exactly what permission is missing.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from hushh_mcp.one_adk.turn_location import (
    STATE_TURN_LOCATION,
    admit_turn_location,
    get_my_location,
    get_weather,
)
from hushh_mcp.services import google_maps_service
from mcp_modules.log_redaction import install_sensitive_log_filter
from tests.helpers.chat_keys import bound_request_chat_key

# Precise enough to identify a home; the server must only ever hold 2 decimals.
PRECISE = {"status": "available", "latitude": 37.774929, "longitude": -122.419416}


def _context(reference: str = "") -> SimpleNamespace:
    return SimpleNamespace(state={STATE_TURN_LOCATION: reference} if reference else {})


@pytest.mark.parametrize("unlocked", [True, False])
async def test_route_admits_location_only_as_an_opaque_turn_reference(monkeypatch, unlocked):
    from fastapi import HTTPException
    from starlette.requests import Request

    from api.routes.one import agent_chat
    from tests.test_agui_turn_timing import _input

    vault = AsyncMock(return_value={"user_id": "owner", "token": "synthetic"})
    if not unlocked:
        vault.side_effect = HTTPException(status_code=403)
    monkeypatch.setattr(agent_chat, "require_vault_owner_token", vault)
    monkeypatch.setattr(agent_chat, "verify_firebase_bearer", lambda _: "owner")
    monkeypatch.setattr(
        agent_chat._session_service, "is_legacy_session", AsyncMock(return_value=False)
    )
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer synthetic")]})
    run = _input()
    run.forwarded_props = {"turnLocation": dict(PRECISE)}
    with bound_request_chat_key("owner"):
        state = await agent_chat._extract_state(request, run)

    # Removed before the bridge can copy or serialize forwarded props.
    assert "turnLocation" not in run.forwarded_props
    serialized = json.dumps(state)
    for fragment in ("37.77", "-122.4", "latitude"):
        assert fragment not in serialized
    result = await get_my_location(SimpleNamespace(state=state))
    if unlocked:
        assert state[STATE_TURN_LOCATION].startswith("one_secret_ref:")
        assert result == {
            "status": "available",
            "latitude": 37.77,
            "longitude": -122.42,
            "precision": "approximate, about 1 km",
        }
    else:
        # A pre-vault turn never keeps it.
        assert state[STATE_TURN_LOCATION] == ""
        assert result["status"] == "needs_location_permission"


async def test_admission_rounds_and_rejects_malformed_positions():
    reference = admit_turn_location({"turnLocation": dict(PRECISE)})
    assert await get_my_location(_context(reference)) == {
        "status": "available",
        "latitude": 37.77,
        "longitude": -122.42,
        "precision": "approximate, about 1 km",
    }
    for bad in (
        {"status": "available", "latitude": 91, "longitude": 0},
        {"status": "available", "latitude": True, "longitude": 0},
        {"status": "available", "latitude": float("nan"), "longitude": 0},
        {"status": "granted"},
        "37.77,-122.42",
    ):
        assert admit_turn_location({"turnLocation": bad}) == ""


@pytest.mark.parametrize(
    ("device_state", "expected"),
    [(None, "not_provided"), ("denied", "denied"), ("not_granted", "not_granted")],
)
async def test_without_a_turn_location_both_tools_ask_for_the_missing_permission(
    monkeypatch, device_state, expected
):
    maps = AsyncMock()
    monkeypatch.setattr(google_maps_service.GoogleMapsService, "current_weather", maps)
    reference = (
        admit_turn_location({"turnLocation": {"status": device_state}}) if device_state else ""
    )
    for tool in (get_my_location, get_weather):
        result = await tool(_context(reference))
        assert result["status"] == "needs_location_permission"
        assert result["permission"] == expected
        assert result["message"]
    maps.assert_not_awaited()


async def test_weather_request_is_built_from_the_coarse_turn_location(monkeypatch, caplog):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "isDaytime": True,
                "timeZone": {"id": "America/Los_Angeles"},
                "weatherCondition": {"description": {"text": "Sunny"}},
                "temperature": {"degrees": 56.6, "unit": "FAHRENHEIT"},
                "feelsLikeTemperature": {"degrees": 55.7, "unit": "FAHRENHEIT"},
                "relativeHumidity": 42,
                "precipitation": {"probability": {"percent": 0}},
                "wind": {"speed": {"value": 5, "unit": "MILES_PER_HOUR"}},
                "currentConditionsHistory": {
                    "maxTemperature": {"degrees": 61, "unit": "FAHRENHEIT"},
                    "minTemperature": {"degrees": 50, "unit": "FAHRENHEIT"},
                },
            },
        )

    monkeypatch.setattr(google_maps_service, "GOOGLE_MAPS_API_KEY", "synthetic-maps-key")
    monkeypatch.setattr(
        google_maps_service,
        "_async_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    install_sensitive_log_filter()  # as server.py installs it
    caplog.set_level(logging.DEBUG)
    reference = admit_turn_location({"turnLocation": dict(PRECISE)})

    result = await get_weather(_context(reference), units="imperial")

    assert len(seen) == 1
    sent = seen[0]
    assert sent.method == "GET"
    assert str(sent.url.copy_with(query=None)) == (
        "https://weather.googleapis.com/v1/currentConditions:lookup"
    )
    assert dict(sent.url.params) == {
        "key": "synthetic-maps-key",
        "location.latitude": "37.77",
        "location.longitude": "-122.42",
        "unitsSystem": "IMPERIAL",
    }
    assert result == {
        "status": "ok",
        "condition": "Sunny",
        "temperature": {"value": 56.6, "unit": "FAHRENHEIT"},
        "feels_like": {"value": 55.7, "unit": "FAHRENHEIT"},
        "high": {"value": 61, "unit": "FAHRENHEIT"},
        "low": {"value": 50, "unit": "FAHRENHEIT"},
        "humidity_percent": 42,
        "precipitation_chance_percent": 0,
        "wind": {"value": 5, "unit": "MILES_PER_HOUR"},
        "is_daytime": True,
        "time_zone": "America/Los_Angeles",
    }
    assert "37.77" not in caplog.text and "122.4" not in caplog.text


async def test_disabled_weather_api_falls_back_without_logging_the_location(monkeypatch, caplog):
    monkeypatch.setattr(google_maps_service, "GOOGLE_MAPS_API_KEY", "synthetic-maps-key")
    monkeypatch.setattr(
        google_maps_service,
        "_async_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: httpx.Response(403, json={}))
        ),
    )
    install_sensitive_log_filter()  # as server.py installs it
    caplog.set_level(logging.DEBUG)
    reference = admit_turn_location({"turnLocation": dict(PRECISE)})

    result = await get_weather(_context(reference))

    assert result["status"] == "unavailable"
    assert (result["latitude"], result["longitude"]) == (37.77, -122.42)
    assert "37.77" not in caplog.text and "122.4" not in caplog.text
