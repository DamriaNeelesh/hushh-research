-- 913 (PARKED): One chat history BYOK cutover. Delete chat history sealed with the
-- platform key.
--
-- PARKED ON PURPOSE. Every deploy lane replays the release manifest, so a
-- registered copy of this file would delete rows on the first deploy after merge
-- and again on every deploy after that. It is not in
-- db/release_migration_manifest.json and must not be added until the founder
-- approves the cutover for a named environment. Guard:
-- tests/test_chat_history_cutover_migration.py. When un-parked it takes the next
-- free release number; the checksum is the approved text.
--
-- What it removes. Since the chat-history BYOK change, every chat ciphertext is
-- sealed with a key derived from the person's vault and starts with the marker
-- 'hussh-chat-v1:'. A row without the marker was sealed with the process-wide
-- platform key (VAULT_DATA_KEY), which Hussh can read. Founder decision
-- (2026-09-26): delete those rows; do not migrate them (re-sealing would need
-- every person's vault key at once). The new code already treats them as absent,
-- so deleting them changes nothing a person can see.
--
-- What it deliberately keeps.
--   * one_capability_runs: task slots stay on the platform key because Location
--     onboarding runs before a vault exists. Not chat history; not touched here.
--   * Every person-key row. Nothing below matches the marker.
--
-- Cascades the founder must accept before approval. Deleting a platform-key
-- conversation or session also deletes, through existing foreign keys:
--   * one_agent_message_feedback rows for that session (migration 197);
--   * one_action_directive_ledger rows that point at it: channel 'adk_chat'
--     (migration 248) and channel 'typed_chat' (migration 114). These hold
--     metadata only, but settled rows are the signed record of actions taken.
--
-- How to run, once approved, in one session against the approved environment:
--   SET hussh.chat_history_cutover = 'approved';
--   \i 913_one_chat_history_legacy_cutover.sql
-- Without that setting the file does nothing. It refuses (RAISE) instead of
-- deleting when any guard below finds live state. Re-running finds nothing.
-- Before approval, prove it against a schema-only dump of the real environment
-- restored into a throwaway Postgres (live databases can hold foreign keys the
-- repository does not declare).

DO $$
DECLARE
  approved TEXT := COALESCE(current_setting('hussh.chat_history_cutover', true), '');
  blocking BIGINT;
BEGIN
  IF approved <> 'approved' THEN
    RAISE NOTICE 'chat history cutover skipped: hussh.chat_history_cutover is not approved';
    RETURN;
  END IF;

  -- 1. A person-key message must never sit under a platform-key conversation:
  --    deleting that conversation would cascade into a record this keeps.
  SELECT COUNT(*) INTO blocking
  FROM agent_chat_messages AS m
  JOIN agent_chat_conversations AS c ON c.id = m.conversation_id
  WHERE m.content_ciphertext LIKE 'hussh-chat-v1:%'
    AND (c.title_ciphertext IS NULL OR c.title_ciphertext NOT LIKE 'hussh-chat-v1:%');
  IF blocking > 0 THEN
    RAISE EXCEPTION 'chat history cutover refused: % person-key message(s) under platform-key conversations', blocking;
  END IF;

  -- 2. A platform-key row written in the last 15 minutes means a writer running
  --    the old code is still live. Finish the rollout first.
  SELECT
    (SELECT COUNT(*) FROM one_adk_sessions
      WHERE payload_ciphertext NOT LIKE 'hussh-chat-v1:%'
        AND updated_at > NOW() - INTERVAL '15 minutes')
    + (SELECT COUNT(*) FROM agent_chat_messages
      WHERE content_ciphertext NOT LIKE 'hussh-chat-v1:%'
        AND created_at > NOW() - INTERVAL '15 minutes')
    + (SELECT COUNT(*) FROM agent_chat_conversations
      WHERE (title_ciphertext IS NULL OR title_ciphertext NOT LIKE 'hussh-chat-v1:%')
        AND updated_at > NOW() - INTERVAL '15 minutes')
  INTO blocking;
  IF blocking > 0 THEN
    RAISE EXCEPTION 'chat history cutover refused: % platform-key row(s) written in the last 15 minutes', blocking;
  END IF;

  -- 3. A live platform-key command checkpoint is an in-flight command.
  SELECT COUNT(*) INTO blocking
  FROM one_adk_sessions
  WHERE app_name = 'one.location.commands.v1'
    AND payload_ciphertext NOT LIKE 'hussh-chat-v1:%'
    AND command_status IN ('ready', 'admitted')
    AND created_at > NOW() - INTERVAL '24 hours';
  IF blocking > 0 THEN
    RAISE EXCEPTION 'chat history cutover refused: % live platform-key command checkpoint(s)', blocking;
  END IF;

  -- 4. An unexpired issued/confirmed directive whose parent would be deleted is
  --    an approval a person may still act on.
  SELECT
    (SELECT COUNT(*) FROM one_action_directive_ledger AS d
      JOIN one_adk_sessions AS s
        ON s.app_name = d.adk_app_name AND s.user_id = d.user_id AND s.session_id = d.session_id
      WHERE d.channel = 'adk_chat' AND d.state IN ('issued', 'confirmed')
        AND d.expires_at > NOW()
        AND s.payload_ciphertext NOT LIKE 'hussh-chat-v1:%')
    + (SELECT COUNT(*) FROM one_action_directive_ledger AS d
      JOIN agent_chat_conversations AS c ON c.id = d.conversation_id
      WHERE d.channel = 'typed_chat' AND d.state IN ('issued', 'confirmed')
        AND d.expires_at > NOW()
        AND (c.title_ciphertext IS NULL OR c.title_ciphertext NOT LIKE 'hussh-chat-v1:%'))
  INTO blocking;
  IF blocking > 0 THEN
    RAISE EXCEPTION 'chat history cutover refused: % unexpired directive(s) on platform-key history', blocking;
  END IF;

  DELETE FROM agent_chat_messages
  WHERE content_ciphertext NOT LIKE 'hussh-chat-v1:%';

  DELETE FROM agent_chat_conversations
  WHERE title_ciphertext IS NULL OR title_ciphertext NOT LIKE 'hussh-chat-v1:%';

  -- ONE chat sessions and command checkpoints (app_name 'one.location.commands.v1').
  DELETE FROM one_adk_sessions
  WHERE payload_ciphertext NOT LIKE 'hussh-chat-v1:%';
END
$$;
