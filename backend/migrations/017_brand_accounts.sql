-- 017: DB-backed brand account registry (campus channel expansion).
--
-- Replaces the .env-only account list (BRAND_IG_EXTRA_ACCOUNTS + per-name
-- vars) as the source of truth for which owned/collab IG accounts the
-- nightly jobs pull. Env-defined accounts keep working as a fallback; a DB
-- row with the same `account` name overrides the env entry. Onboard new
-- campus channels with scripts/add_brand_account.py — no .env edit, no
-- deploy.
--
-- Apply by hand (same as all migrations here):
--   psql -h localhost -U niltv_user -d niltv_db -f backend/migrations/017_brand_accounts.sql

CREATE TABLE IF NOT EXISTS brand_accounts (
    id                 SERIAL PRIMARY KEY,
    account            TEXT UNIQUE NOT NULL,     -- discriminator; matches brand_posts.account / brand_snapshots.account
    username           TEXT,                     -- IG @handle (informational)
    ig_user_id         TEXT NOT NULL,            -- numeric IG user id ("me" for Instagram-Login tokens)
    access_token       TEXT,                     -- NULL = same-portfolio fallback to BRAND_IG_ACCESS_TOKEN
    api                TEXT NOT NULL DEFAULT 'fb',  -- 'fb' = graph.facebook.com, 'ig' = graph.instagram.com (host-locked tokens)
    post_limit         INTEGER NOT NULL DEFAULT 25, -- media fetched per nightly run
    campus             TEXT,                     -- school/node grouping, e.g. 'duke'
    network_pull       BOOLEAN NOT NULL DEFAULT FALSE, -- include in the collab/network job (fb api only)
    active             BOOLEAN NOT NULL DEFAULT TRUE,
    token_expires_at   TIMESTAMPTZ,
    token_refreshed_at TIMESTAMPTZ,
    notes              TEXT,
    created_at         TIMESTAMPTZ DEFAULT now(),
    updated_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_brand_accounts_active ON brand_accounts(active);
