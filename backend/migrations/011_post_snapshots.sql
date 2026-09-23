-- 011: Add athlete_post_snapshots table for tracking post engagement over time.
-- Each row captures like_count and comment_count at a point in time.

CREATE TABLE IF NOT EXISTS athlete_post_snapshots (
    id              SERIAL PRIMARY KEY,
    post_id         INTEGER NOT NULL REFERENCES athlete_posts(id) ON DELETE CASCADE,
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    like_count      INTEGER,
    comment_count   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_post_snapshots_post_id ON athlete_post_snapshots(post_id);
CREATE INDEX IF NOT EXISTS idx_post_snapshots_captured_at ON athlete_post_snapshots(captured_at);
