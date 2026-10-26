-- 031: Per-account session version.
--
-- Every dashboard session carries the version it was issued under and sends it
-- with each API call. Changing a password, an admin password reset or
-- disabling the account bumps it, which ends every session issued before.
--
-- Applied automatically by scripts/migrate.py on deploy.

ALTER TABLE dashboard_users ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 1;
