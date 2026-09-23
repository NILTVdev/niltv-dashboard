-- 012: Add niltv_network_posts and niltv_network_post_snapshots tables.
-- Tracks posts from NILTV collab accounts imported via Zoomph CSV,
-- plus point-in-time metric snapshots for trending over time.

CREATE TABLE IF NOT EXISTS niltv_network_posts (
    id              SERIAL PRIMARY KEY,
    post_id         TEXT UNIQUE NOT NULL,
    account_username TEXT,
    account_name    TEXT,
    description     TEXT,
    duration_sec    INTEGER,
    publish_time    TIMESTAMPTZ,
    permalink       TEXT,
    post_type       TEXT,
    views           INTEGER,
    likes           INTEGER,
    shares          INTEGER,
    comments        INTEGER,
    saves           INTEGER,
    reach           INTEGER,
    projected_reach INTEGER,
    follows         INTEGER,
    imported_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_niltv_network_posts_publish ON niltv_network_posts(publish_time);

CREATE TABLE IF NOT EXISTS niltv_network_post_snapshots (
    id              SERIAL PRIMARY KEY,
    network_post_id INTEGER NOT NULL REFERENCES niltv_network_posts(id) ON DELETE CASCADE,
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    views           INTEGER,
    likes           INTEGER,
    shares          INTEGER,
    comments        INTEGER,
    saves           INTEGER,
    reach           INTEGER,
    projected_reach INTEGER,
    follows         INTEGER
);

CREATE INDEX IF NOT EXISTS idx_niltv_network_snap_post_captured ON niltv_network_post_snapshots(network_post_id, captured_at);
