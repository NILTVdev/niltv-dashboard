-- 020: Ambassador registry.
--
-- Ambassadors are discovered from the "welcome our new ambassador @x" posts
-- on @niltv (parsed from brand_posts captions by backend/jobs/ambassadors.py)
-- and can also be added/removed by hand through the admin endpoints. Their
-- collab content is attributed on niltv_network_posts / trueblue_network_posts
-- via the ambassador_id column added in migration 022 — their own (non-collab)
-- post history is never copied.
--
-- Apply by hand (same as all migrations here):
--   psql -h localhost -U niltv_user -d niltv_db -f backend/migrations/020_ambassadors.sql

CREATE TABLE IF NOT EXISTS ambassadors (
    id                 SERIAL PRIMARY KEY,
    ig_username        TEXT UNIQUE NOT NULL,     -- lowercased; matches network posts' account_username
    display_name       TEXT,
    previous_usernames TEXT,                     -- comma list; audit trail across IG handle renames
    campus             TEXT,                     -- school/node grouping; matches brand_accounts.campus
    campus_source      TEXT NOT NULL DEFAULT 'inferred'
                       CHECK (campus_source IN ('inferred', 'manual')),  -- manual always wins over inference
    status             TEXT NOT NULL DEFAULT 'candidate'
                       CHECK (status IN ('candidate', 'confirmed', 'removed')),
    source             TEXT,                     -- 'welcome_post' | 'admin'
    welcome_post_id    TEXT,                     -- brand_posts.ig_post_id of the announcing post
    announced_at       TIMESTAMPTZ,              -- posted_at of the welcome post
    athlete_id         INTEGER REFERENCES athletes(id) ON DELETE SET NULL,  -- set when also on a tracked roster
    -- Business Discovery enrichment (profile fields only, no media)
    ig_user_id         TEXT,
    ig_accessible      BOOLEAN DEFAULT TRUE,     -- FALSE = personal account, Business Discovery fails
    ig_checked_at      TIMESTAMPTZ,
    -- Precomputed cache (updated after each cron job, not on every request)
    cached_followers          INTEGER,
    cached_bio                TEXT,
    cached_collab_posts       INTEGER,
    cached_collab_views       INTEGER,
    cached_collab_engagement  INTEGER,           -- likes + comments + shares + saves across attributed posts
    cached_last_pulled        TIMESTAMPTZ,
    active             BOOLEAN NOT NULL DEFAULT TRUE,
    notes              TEXT,
    created_at         TIMESTAMPTZ DEFAULT now(),
    updated_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ambassadors_status ON ambassadors(status);
CREATE INDEX IF NOT EXISTS idx_ambassadors_campus ON ambassadors(campus);
