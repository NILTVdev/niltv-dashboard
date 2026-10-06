-- 029: Individual dashboard accounts with roles.
--
-- Replaces the single shared DASHBOARD_USERNAME / DASHBOARD_PASSWORD login.
-- Each person signs in with their own row here; the role decides what they
-- can reach, and the backend enforces it on the API routes:
--
--   viewer      data screens only
--   onboarding  viewer + the athlete onboarding workflow
--   admin       everything, including the admin page and managing users
--
-- password_hash is "pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>".
-- session_version is bumped whenever a user's role or password changes, which
-- invalidates every session token issued before the change.
--
-- The first admin is created from the command line:
--   python -m scripts.dashboard_user add <username> --role admin
--
-- Applied automatically by scripts/migrate.py on deploy.

CREATE TABLE IF NOT EXISTS dashboard_users (
    id               SERIAL PRIMARY KEY,
    username         TEXT NOT NULL UNIQUE,
    password_hash    TEXT NOT NULL,
    role             TEXT NOT NULL CHECK (role IN ('viewer', 'onboarding', 'admin')),
    session_version  INTEGER NOT NULL DEFAULT 1,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at    TIMESTAMPTZ
);
