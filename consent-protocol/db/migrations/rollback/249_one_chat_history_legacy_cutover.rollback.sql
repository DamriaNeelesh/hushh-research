-- Rollback for migration 249: intentionally a no-op.
--
-- 249 deletes chat history sealed with the platform key. That deletion is the
-- founder-approved cutover to person-key chat history and cannot be undone by
-- SQL: the rows are gone. Restoring them means restoring the database from
-- backup (production: Cloud SQL backups and PITR), and even then the person-key
-- code treats platform-key rows as absent and never opens them. Rolling the
-- application back to the platform-key code does not need these rows restored;
-- it starts new history.

SELECT 1;
