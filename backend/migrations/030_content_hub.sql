-- 030: Athlete Content Hub: asks, claims, submissions.
--
-- Staff post content asks (Training Table Trivia, a podcast pitch, a day in
-- the life). Athletes browse them on the website hub, claim the ones they
-- will do, and submit a link to the finished post. Three tables keep the
-- still-open product decisions open:
--
--   * an ask's spot limit is nullable: NULL means any number of athletes may
--     claim it, a number caps it (1 = one athlete);
--   * submissions are one row per link, so a claim may hold one link or
--     several; a superseded link is kept with replaced_at set;
--   * who may claim is decided in code (the applications row is the
--     athlete's identity, since the site account email is the application
--     email), not by this schema.
--
-- Personal data stays on applications; these tables hold only ids, the
-- staff-written ask text, and the athlete's submitted link and note.
--
-- Applied automatically by scripts/migrate.py on deploy.

CREATE TABLE IF NOT EXISTS hub_asks (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    category    TEXT,                                   -- short label: Trivia, Podcast, Lifestyle
    summary     TEXT,                                   -- one or two sentences
    steps       JSONB NOT NULL DEFAULT '[]'::jsonb,     -- ordered list of short strings ("Film vertical, 30 to 60 seconds")
    due_on      DATE,                                   -- NULL = no deadline
    slots       INTEGER CHECK (slots IS NULL OR slots > 0),   -- NULL = open to all athletes
    status      TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('draft', 'open', 'closed')),
    created_by  TEXT,                                   -- staff label; a user id once dashboard accounts exist
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ,
    closed_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_hub_asks_status ON hub_asks(status, due_on);

CREATE TABLE IF NOT EXISTS hub_claims (
    id              SERIAL PRIMARY KEY,
    ask_id          INTEGER NOT NULL REFERENCES hub_asks(id) ON DELETE CASCADE,
    application_id  INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    account_sub     TEXT,                               -- the site account that claimed it
    status          TEXT NOT NULL DEFAULT 'claimed'
                    CHECK (status IN ('claimed', 'submitted', 'released')),
    claimed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at    TIMESTAMPTZ,
    released_at     TIMESTAMPTZ,                        -- set when the athlete unclaims; re-claiming reuses the row
    UNIQUE (ask_id, application_id)
);

CREATE INDEX IF NOT EXISTS idx_hub_claims_application ON hub_claims(application_id, status);
CREATE INDEX IF NOT EXISTS idx_hub_claims_ask ON hub_claims(ask_id, status);

CREATE TABLE IF NOT EXISTS hub_submissions (
    id            SERIAL PRIMARY KEY,
    claim_id      INTEGER NOT NULL REFERENCES hub_claims(id) ON DELETE CASCADE,
    url           TEXT NOT NULL,
    note          TEXT,
    submitted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    replaced_at   TIMESTAMPTZ                           -- a later link superseded this one; NULL = current
);

CREATE INDEX IF NOT EXISTS idx_hub_submissions_claim ON hub_submissions(claim_id, submitted_at);
