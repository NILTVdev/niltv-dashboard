-- Add snapshot history tracking for Zoomph posts and updated_at column.
-- Run:  psql -h 127.0.0.1 -U niltv_user -d niltv_db -f backend/migrations/005_zoomph_snapshots.sql

-- Track when a post was last updated by the cron job
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

-- Point-in-time engagement snapshots for each Zoomph post
CREATE TABLE IF NOT EXISTS zoomph_post_snapshots (
    id SERIAL PRIMARY KEY,
    zoomph_post_id INTEGER NOT NULL REFERENCES zoomph_posts(id) ON DELETE CASCADE,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Engagement
    engagement INTEGER,
    like_count INTEGER,
    comment_count INTEGER,
    save_count INTEGER,
    share_count INTEGER,
    reply_count INTEGER,
    -- Reach / rates
    impressions INTEGER,
    reach INTEGER,
    projected_impressions BIGINT,
    follower_count INTEGER,
    engagement_rate NUMERIC,
    follower_interaction_rate NUMERIC,
    -- Value
    brand_exposure_value NUMERIC,
    post_value NUMERIC,
    brand_exposure_value_us NUMERIC,
    -- Video / streaming
    vod_views INTEGER,
    view_count INTEGER,
    live_views INTEGER,
    hours_watched BIGINT
);

-- Fast lookups: all snapshots for a post ordered by time
CREATE INDEX IF NOT EXISTS idx_zoomph_snapshots_post_time
    ON zoomph_post_snapshots(zoomph_post_id, captured_at DESC);
