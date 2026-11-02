-- 032: Community Star applications (niltv.com/communitystar).
--
-- One row per application to the Community Star grant program. Separate from
-- the athlete onboarding table (025): a Community Star applicant is not an
-- ambassador, never goes through DocuSign or Stripe, and the athlete signup's
-- upsert-on-email would overwrite one with the other.
--
-- One application per email per season (UNIQUE season + email); a second
-- post with the same email is refused, never merged.
--
-- Personal data (email, phone, answers) lives ONLY here and in the staff
-- sheet mirror. Nothing in this table is served to the public website.
--
-- Applied automatically by scripts/migrate.py on deploy.

CREATE TABLE IF NOT EXISTS community_star_applications (
    id                  SERIAL PRIMARY KEY,
    season              TEXT NOT NULL DEFAULT '2026',

    -- identity (email always lowercased)
    email               TEXT NOT NULL,
    full_name           TEXT NOT NULL,
    phone               TEXT NOT NULL,

    -- school + sport
    school              TEXT NOT NULL,
    school_state        TEXT,
    school_domain       TEXT,
    school_matched      BOOLEAN NOT NULL DEFAULT FALSE,   -- picked from the list vs typed
    sport               TEXT NOT NULL,
    class_year          TEXT NOT NULL,                    -- Fr | So | Jr | Sr | Grad

    -- the entry
    instagram           TEXT NOT NULL,                    -- handle, lowercase, no @
    post_url            TEXT NOT NULL,                    -- normalized instagram.com post/reel link
    community           TEXT NOT NULL,
    work                TEXT NOT NULL,                    -- "What you're already doing there"
    organization        TEXT,

    -- required attestations
    collab_invited      BOOLEAN NOT NULL DEFAULT FALSE,
    eligible_and_rules  BOOLEAN NOT NULL DEFAULT FALSE,
    confirm_age         BOOLEAN NOT NULL DEFAULT FALSE,
    consent_privacy     BOOLEAN NOT NULL DEFAULT FALSE,

    -- optional opt-ins (separate, per the forms consent rule)
    consent_email       BOOLEAN NOT NULL DEFAULT FALSE,
    consent_sms         BOOLEAN NOT NULL DEFAULT FALSE,
    consent_partners    BOOLEAN NOT NULL DEFAULT FALSE,
    consent_version     TEXT,

    -- provenance
    source              TEXT NOT NULL DEFAULT 'communitystar',
    utm                 JSONB,
    answers             JSONB,                            -- full raw payload
    user_agent          TEXT,
    ip                  TEXT,
    confirmation_sent   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_community_star_season_email UNIQUE (season, email)
);

CREATE INDEX IF NOT EXISTS idx_community_star_created ON community_star_applications(season, created_at);
