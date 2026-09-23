-- Run this once against niltv_db after connecting:
--   psql -U niltv_user -d niltv_db -f backend/migrations/001_initial_schema.sql

CREATE TABLE IF NOT EXISTS athletes (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    sport       TEXT,
    year        TEXT,
    ig_handle   TEXT UNIQUE,
    ig_user_id  TEXT,
    tiktok_handle TEXT,
    x_handle    TEXT,
    active      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS athlete_snapshots (
    id          SERIAL PRIMARY KEY,
    athlete_id  INT NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    pulled_at   TIMESTAMPTZ DEFAULT NOW(),
    ig_followers    INT,
    ig_posts        INT,
    ig_bio          TEXT,
    tiktok_followers INT,
    tiktok_likes     BIGINT,
    x_followers     INT,
    x_posts         INT
);

CREATE TABLE IF NOT EXISTS athlete_posts (
    id            SERIAL PRIMARY KEY,
    athlete_id    INT NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    pulled_at     TIMESTAMPTZ DEFAULT NOW(),
    ig_post_id    TEXT UNIQUE,
    posted_at     TIMESTAMPTZ,
    media_type    TEXT,
    like_count    INT,
    comment_count INT,
    permalink     TEXT,
    caption       TEXT,
    media_url     TEXT
);

CREATE TABLE IF NOT EXISTS zoomph_posts (
    id                   SERIAL PRIMARY KEY,
    pulled_at            TIMESTAMPTZ DEFAULT NOW(),
    post_id              TEXT UNIQUE,
    partner              TEXT,
    platform             TEXT,
    content_type         TEXT,
    author               TEXT,
    url                  TEXT,
    message              TEXT,
    engagement           INT,
    like_count           INT,
    impressions          INT,
    brand_exposure_value NUMERIC,
    vod_views            INT,
    posted_at            TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS pull_run_logs (
    id               SERIAL PRIMARY KEY,
    job_name         TEXT NOT NULL,
    started_at       TIMESTAMPTZ DEFAULT NOW(),
    finished_at      TIMESTAMPTZ,
    status           TEXT,
    records_inserted INT DEFAULT 0,
    error_message    TEXT
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_athlete_snapshots_athlete_id ON athlete_snapshots(athlete_id);
CREATE INDEX IF NOT EXISTS idx_athlete_snapshots_pulled_at  ON athlete_snapshots(pulled_at DESC);
CREATE INDEX IF NOT EXISTS idx_athlete_posts_athlete_id     ON athlete_posts(athlete_id);
CREATE INDEX IF NOT EXISTS idx_athlete_posts_posted_at      ON athlete_posts(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_zoomph_posts_pulled_at       ON zoomph_posts(pulled_at DESC);
CREATE INDEX IF NOT EXISTS idx_zoomph_posts_platform        ON zoomph_posts(platform);
CREATE INDEX IF NOT EXISTS idx_pull_run_logs_job_name       ON pull_run_logs(job_name);
