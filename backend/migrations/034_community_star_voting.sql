-- 034: Community Star public cards, program state, and fan votes.
--
-- community_star_applications.card_*: what the public finalist card shows when
-- it should differ from the application; empty falls back to the application.
--
-- community_star_program: one row per season. The publish times are the only
-- way a name, the top 5, or the winners reach niltv.com: marking a row Finalist
-- publishes nothing. settings holds the voting policy staff can change.
-- frozen_board is the leaderboard stored once when voting closes (rank, id and
-- name only). dev_now is a rehearsal clock, ignored in production.
--
-- community_star_votes: one fact row per voter per season, unique on the
-- normalised email (official rules: one vote per person). A vote counts only
-- once a person presses Confirm my vote. token_hash is sha256; the raw token
-- exists only in the email and is created when the outbox sends it. Tallies are
-- always recomputed from these rows.
--
-- Applied automatically by scripts/migrate.py on deploy.

ALTER TABLE community_star_applications
    ADD COLUMN IF NOT EXISTS card_name      TEXT,
    ADD COLUMN IF NOT EXISTS card_school    TEXT,
    ADD COLUMN IF NOT EXISTS card_sport     TEXT,
    ADD COLUMN IF NOT EXISTS card_community TEXT;

CREATE TABLE IF NOT EXISTS community_star_program (
    season                 TEXT PRIMARY KEY,
    finalists_published_at TIMESTAMPTZ,
    top5_published_at      TIMESTAMPTZ,
    winners_published_at   TIMESTAMPTZ,
    published_by           TEXT,
    settings               JSONB NOT NULL DEFAULT '{}',
    frozen_board           JSONB,
    frozen_at              TIMESTAMPTZ,
    dev_now                TIMESTAMPTZ,
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS community_star_votes (
    id                 SERIAL PRIMARY KEY,
    season             TEXT NOT NULL,
    finalist_id        INTEGER NOT NULL REFERENCES community_star_applications(id),
    email              TEXT NOT NULL,
    email_norm         TEXT NOT NULL,
    token_hash         TEXT,
    token_expires      TIMESTAMPTZ,
    status             TEXT NOT NULL DEFAULT 'pending',
    void_reason        TEXT,
    voided_by          TEXT,
    voided_at          TIMESTAMPTZ,
    restored_by        TEXT,
    restored_at        TIMESTAMPTZ,
    ip                 TEXT,
    user_agent         TEXT,
    confirm_ip         TEXT,
    confirm_user_agent TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_at       TIMESTAMPTZ,
    mail_status        TEXT NOT NULL DEFAULT 'queued',
    mail_attempts      INTEGER NOT NULL DEFAULT 0,
    mail_next_at       TIMESTAMPTZ,
    mail_last_error    TEXT,
    sends              INTEGER NOT NULL DEFAULT 0,
    last_sent_at       TIMESTAMPTZ,
    CONSTRAINT uq_community_star_vote_email UNIQUE (season, email_norm),
    CONSTRAINT ck_community_star_vote_status CHECK (status IN ('pending', 'confirmed', 'void')),
    CONSTRAINT ck_community_star_vote_mail CHECK (mail_status IN ('queued', 'sent', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_community_star_votes_tally
    ON community_star_votes(season, status, finalist_id);
CREATE INDEX IF NOT EXISTS idx_community_star_votes_outbox
    ON community_star_votes(mail_next_at) WHERE mail_status = 'queued';
CREATE UNIQUE INDEX IF NOT EXISTS uq_community_star_vote_token
    ON community_star_votes(token_hash) WHERE token_hash IS NOT NULL;
