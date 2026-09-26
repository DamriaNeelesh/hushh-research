"""The chat-history BYOK cutover migration is parked, gated, and deletes only legacy rows.

Static checks always run. The executable checks run when
``CHAT_CUTOVER_TEST_DATABASE_URL`` points at a THROWAWAY Postgres holding the real
schema (for example a schema-only dump restored locally). Every scenario runs in a
transaction that is rolled back.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PARKED = ROOT / "db/migrations/parked/913_one_chat_history_legacy_cutover.sql"
MANIFEST = ROOT / "db/release_migration_manifest.json"
MARKER = "hussh-chat-v1:"


def _sql() -> str:
    return PARKED.read_text()


def test_cutover_is_parked_and_never_in_the_release_manifest() -> None:
    assert PARKED.exists()
    assert not (ROOT / "db/migrations" / PARKED.name).exists()
    manifest = MANIFEST.read_text()
    assert "chat_history_legacy_cutover" not in manifest
    parsed = json.loads(manifest)
    listed = set(parsed.get("ordered_migrations", []))
    for overlay in parsed.get("environment_overlays", {}).values():
        listed.update(overlay)
    listed.update(parsed.get("rollback_migrations", {}))
    assert not any("cutover" in name and "chat" in name for name in listed)


def test_cutover_is_gated_and_every_delete_targets_only_unmarked_rows() -> None:
    sql = _sql()
    assert "current_setting('hussh.chat_history_cutover', true)" in sql
    assert "IF approved <> 'approved' THEN" in sql
    deletes = re.findall(r"DELETE FROM\s+(\w+)\s+WHERE([^;]+);", sql)
    assert {table for table, _ in deletes} == {
        "agent_chat_messages",
        "agent_chat_conversations",
        "one_adk_sessions",
    }
    for _table, where in deletes:
        assert f"NOT LIKE '{MARKER}%'" in where
    assert "one_capability_runs" not in {table for table, _ in deletes}
    assert "DROP " not in sql.upper().replace("DROP CONSTRAINT", "")


# ── Executable proof against a throwaway database ─────────────────────────────

DATABASE_URL = os.getenv("CHAT_CUTOVER_TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DATABASE_URL, reason="CHAT_CUTOVER_TEST_DATABASE_URL not set")


@pytest.fixture
def conn() -> Iterator:
    psycopg2 = pytest.importorskip("psycopg2")
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _run(conn, *, approved: bool) -> None:  # noqa: ANN001
    with conn.cursor() as cursor:
        if approved:
            cursor.execute("SET LOCAL hussh.chat_history_cutover = 'approved'")
        cursor.execute(_sql())


def _seed(conn, *, stale_legacy: bool = True) -> dict:  # noqa: ANN001
    owner = f"cutover-{uuid.uuid4().hex[:12]}"
    ids = {
        "owner": owner,
        "legacy_conversation": str(uuid.uuid4()),
        "new_conversation": str(uuid.uuid4()),
    }
    age = "NOW() - INTERVAL '2 hours'" if stale_legacy else "NOW()"
    with conn.cursor() as cursor:
        cursor.execute(
            """INSERT INTO vault_keys (user_id, created_at, updated_at, vault_status)
               VALUES (%s, 0, 0, 'placeholder')""",
            (owner,),
        )
        cursor.execute("INSERT INTO actor_profiles (user_id) VALUES (%s)", (owner,))
        for session_id, ciphertext in (("legacy-thread", "b2xk"), ("new-thread", MARKER + "bmV3")):
            cursor.execute(
                f"""INSERT INTO one_adk_sessions
                    (app_name, user_id, session_id, payload_ciphertext, payload_iv,
                     payload_tag, created_at, updated_at)
                    VALUES ('hussh_one', %s, %s, %s, 'iv', 'tag', {age}, {age})""",
                (owner, session_id, ciphertext),
            )
            cursor.execute(
                """INSERT INTO one_agent_message_feedback
                   (user_id, app_name, conversation_ref, message_ref, rating)
                   VALUES (%s, 'hussh_one', %s, 'm1', 'up')""",
                (owner, session_id),
            )
        cursor.execute(
            f"""INSERT INTO one_adk_sessions
                (app_name, user_id, session_id, payload_ciphertext, payload_iv, payload_tag,
                 command_status, created_at, updated_at)
                VALUES ('one.location.commands.v1', %s, 'old-command', 'b2xk', 'iv', 'tag',
                        'settled', {age}, {age})""",
            (owner,),
        )
        for key, title in (("legacy_conversation", "b2xk"), ("new_conversation", MARKER + "dA")):
            cursor.execute(
                f"""INSERT INTO agent_chat_conversations
                    (id, user_id, title_ciphertext, title_iv, title_tag, created_at, updated_at)
                    VALUES (%s, %s, %s, 'iv', 'tag', {age}, {age})""",
                (ids[key], owner, title),
            )
            cursor.execute(
                f"""INSERT INTO agent_chat_messages
                    (id, conversation_id, user_id, role, content_ciphertext, content_iv,
                     content_tag, created_at)
                    VALUES (%s, %s, %s, 'user', %s, 'iv', 'tag', {age})""",
                (str(uuid.uuid4()), ids[key], owner, title),
            )
        cursor.execute(
            """INSERT INTO one_capability_runs
               (run_id, user_id, capability_id, capability_version, graph_revision, status,
                idempotency_key, slots_hmac, expires_at, slots_ciphertext, slots_iv,
                slots_tag, slots_algorithm)
               VALUES (%s, %s, 'workflow.location.onboarding', 1, 'g1', 'needs_input',
                       %s, %s, NOW() + INTERVAL '1 day', 'cGxhdGZvcm0', 'iv', 'tag',
                       'aes-256-gcm')""",
            (f"run_{uuid.uuid4().hex}", owner, "a" * 64, "b" * 64),
        )
    return ids


def _counts(conn, owner: str) -> dict:  # noqa: ANN001
    with conn.cursor() as cursor:
        cursor.execute(
            """SELECT
                 (SELECT COUNT(*) FROM one_adk_sessions WHERE user_id = %(o)s
                    AND payload_ciphertext LIKE 'hussh-chat-v1:%%'),
                 (SELECT COUNT(*) FROM one_adk_sessions WHERE user_id = %(o)s
                    AND payload_ciphertext NOT LIKE 'hussh-chat-v1:%%'),
                 (SELECT COUNT(*) FROM agent_chat_conversations WHERE user_id = %(o)s),
                 (SELECT COUNT(*) FROM agent_chat_messages WHERE user_id = %(o)s),
                 (SELECT COUNT(*) FROM one_agent_message_feedback WHERE user_id = %(o)s),
                 (SELECT COUNT(*) FROM one_capability_runs WHERE user_id = %(o)s)""",
            {"o": owner},
        )
        row = cursor.fetchone()
    keys = ("new_sessions", "legacy_sessions", "conversations", "messages", "feedback", "runs")
    return dict(zip(keys, row, strict=True))


@needs_db
def test_without_approval_nothing_is_deleted(conn) -> None:  # noqa: ANN001
    ids = _seed(conn)
    before = _counts(conn, ids["owner"])
    _run(conn, approved=False)
    assert _counts(conn, ids["owner"]) == before


@needs_db
def test_approved_cutover_deletes_only_legacy_rows_and_is_idempotent(conn) -> None:  # noqa: ANN001
    ids = _seed(conn)
    assert _counts(conn, ids["owner"]) == {
        "new_sessions": 1,
        "legacy_sessions": 2,
        "conversations": 2,
        "messages": 2,
        "feedback": 2,
        "runs": 1,
    }
    _run(conn, approved=True)
    after = {
        "new_sessions": 1,
        "legacy_sessions": 0,
        "conversations": 1,
        "messages": 1,
        "feedback": 1,
        "runs": 1,
    }
    assert _counts(conn, ids["owner"]) == after
    _run(conn, approved=True)
    assert _counts(conn, ids["owner"]) == after


@needs_db
def test_person_key_message_under_a_legacy_conversation_refuses(conn) -> None:  # noqa: ANN001
    psycopg2 = pytest.importorskip("psycopg2")
    ids = _seed(conn)
    with conn.cursor() as cursor:
        cursor.execute(
            """INSERT INTO agent_chat_messages
               (id, conversation_id, user_id, role, content_ciphertext, content_iv, content_tag,
                created_at)
               VALUES (%s, %s, %s, 'user', %s, 'iv', 'tag', NOW() - INTERVAL '2 hours')""",
            (str(uuid.uuid4()), ids["legacy_conversation"], ids["owner"], MARKER + "eA"),
        )
    with pytest.raises(psycopg2.Error, match="person-key message"):
        _run(conn, approved=True)


@needs_db
def test_recent_legacy_writes_refuse_until_the_old_code_is_gone(conn) -> None:  # noqa: ANN001
    psycopg2 = pytest.importorskip("psycopg2")
    _seed(conn, stale_legacy=False)
    with pytest.raises(psycopg2.Error, match="last 15 minutes"):
        _run(conn, approved=True)


@needs_db
def test_live_legacy_command_checkpoint_refuses(conn) -> None:  # noqa: ANN001
    psycopg2 = pytest.importorskip("psycopg2")
    ids = _seed(conn)
    with conn.cursor() as cursor:
        cursor.execute(
            """UPDATE one_adk_sessions SET command_status = 'ready'
               WHERE user_id = %s AND app_name = 'one.location.commands.v1'""",
            (ids["owner"],),
        )
    with pytest.raises(psycopg2.Error, match="command checkpoint"):
        _run(conn, approved=True)
