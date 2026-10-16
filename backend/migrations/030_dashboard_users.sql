-- 030: Dashboard accounts, one per person (plus the shared general and demo
-- logins).
--
-- role: admin   = everything, including onboarding, uploads and user management
--       general = analytics pages incl. the athlete roster, read-only
--       demo    = aggregate analytics only, read-only
-- password_hash is scrypt (backend/accounts.py). active = FALSE blocks login
-- and every API call made for that account.
--
-- Applied automatically by scripts/migrate.py on deploy.

CREATE TABLE IF NOT EXISTS dashboard_users (
    id             SERIAL PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    role           TEXT NOT NULL CHECK (role IN ('admin', 'general', 'demo')),
    password_hash  TEXT NOT NULL,
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by     TEXT,
    updated_at     TIMESTAMPTZ,
    last_login_at  TIMESTAMPTZ
);
