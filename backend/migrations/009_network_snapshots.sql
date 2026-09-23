-- Historical metric snapshots for TrueBlue network posts.
-- Run:  psql -h 127.0.0.1 -U niltv_user -d niltv_db -f backend/migrations/009_network_snapshots.sql

-- Track when a network post was last updated
ALTER TABLE trueblue_network_posts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

-- Point-in-time metric snapshots for each network post
CREATE TABLE IF NOT EXISTS trueblue_network_post_snapshots (
    id          SERIAL PRIMARY KEY,
    network_post_id INTEGER NOT NULL REFERENCES trueblue_network_posts(id) ON DELETE CASCADE,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    views       INTEGER,
    likes       INTEGER,
    shares      INTEGER,
    comments    INTEGER,
    saves       INTEGER,
    reach       INTEGER,
    follows     INTEGER
);

-- Fast lookups: all snapshots for a post ordered by time
CREATE INDEX IF NOT EXISTS idx_network_snapshots_post_time
    ON trueblue_network_post_snapshots(network_post_id, captured_at DESC);
