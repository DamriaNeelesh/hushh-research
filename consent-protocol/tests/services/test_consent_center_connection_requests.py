import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from hushh_mcp.services.consent_center_service import ConsentCenterService


def test_person_consent_uses_current_avatar_and_clears_removed_photo():
    svc = ConsentCenterService.__new__(ConsentCenterService)
    svc._identity = MagicMock()
    svc._identity.ensure_many = AsyncMock(
        return_value={
            "person-1": {
                "display_name": "Priya",
                "photo_url": "https://example.test/priya.png",
            },
            "person-2": {"display_name": "Meena", "photo_url": None},
        }
    )

    entries = asyncio.run(
        svc._hydrate_entry_identities(
            [
                {
                    "counterpart_type": "person",
                    "counterpart_id": "person-1",
                    "counterpart_label": "Priya",
                },
                {
                    "counterpart_type": "person",
                    "counterpart_id": "person-2",
                    "counterpart_label": "Meena",
                    "counterpart_image_url": "https://example.test/old.png",
                },
                {
                    "counterpart_type": "developer",
                    "counterpart_id": "app-1",
                    "counterpart_image_url": "https://example.test/logo.png",
                },
            ]
        )
    )

    svc._identity.ensure_many.assert_awaited_once_with(["person-1", "person-2"])
    assert entries[0]["counterpart_image_url"] == "https://example.test/priya.png"
    assert entries[1]["counterpart_image_url"] is None
    assert entries[2]["counterpart_image_url"] == "https://example.test/logo.png"


def test_consents_pending_count_includes_incoming_connection_requests():
    svc = ConsentCenterService.__new__(ConsentCenterService)

    fake_conn = MagicMock()
    fake_conn.list_requests.return_value = [{"id": "req-1"}, {"id": "req-2"}]

    with patch(
        "hushh_mcp.services.consent_center_service.ConnectionsService",
        return_value=fake_conn,
    ):
        count = asyncio.run(svc._incoming_connection_request_count("user-a"))
    assert count == 2
    fake_conn.list_requests.assert_called_once_with("user-a", direction="incoming")


def test_incoming_entries_surface_public_scope_proposals_for_selection():
    """Connection review exposes proposal presentation only, never raw scopes."""
    svc = ConsentCenterService.__new__(ConsentCenterService)

    fake_conn = MagicMock()
    fake_conn.list_requests.return_value = [
        {
            "id": "req-scoped",
            "counterpartUserId": "ria-1",
            "counterpartDisplayName": "Ada RIA",
            "message": "sharing a pick",
            "scopes": [
                {
                    "scopeHandle": "scp_1",
                    "direction": "requested",
                    "label": "RIA Picks",
                    "description": "Use this RIA's published investment picks.",
                    "status": "pending",
                }
            ],
        },
        {
            "id": "req-plain",
            "counterpartUserId": "friend-1",
            # no scopes key at all → plain connect
        },
    ]

    with patch(
        "hushh_mcp.services.consent_center_service.ConnectionsService",
        return_value=fake_conn,
    ):
        entries = asyncio.run(svc._incoming_connection_request_entries("user-a"))

    by_id = {e["id"]: e for e in entries}
    assert by_id["req-scoped"]["metadata"]["scope_proposals"] == [
        {
            "scopeHandle": "scp_1",
            "direction": "requested",
            "label": "RIA Picks",
            "description": "Use this RIA's published investment picks.",
            "status": "pending",
        }
    ]
    assert by_id["req-scoped"]["kind"] == "connection_request"
    assert by_id["req-plain"]["metadata"]["scope_proposals"] == []
    fake_conn.list_requests.assert_called_once_with("user-a", direction="incoming")
