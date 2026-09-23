-- Add precomputed cache columns to athletes table.
-- These are populated by precompute_athlete_cache() after each cron job,
-- eliminating expensive per-request computation.
-- Run:  psql -h 127.0.0.1 -U niltv_user -d niltv_db -f backend/migrations/004_athlete_cache_columns.sql

ALTER TABLE athletes ADD COLUMN IF NOT EXISTS cached_ig_followers INTEGER;
ALTER TABLE athletes ADD COLUMN IF NOT EXISTS cached_ig_posts INTEGER;
ALTER TABLE athletes ADD COLUMN IF NOT EXISTS cached_ig_bio TEXT;
ALTER TABLE athletes ADD COLUMN IF NOT EXISTS cached_ig_engagement INTEGER;
ALTER TABLE athletes ADD COLUMN IF NOT EXISTS cached_attributed_eng INTEGER;
ALTER TABLE athletes ADD COLUMN IF NOT EXISTS cached_social_valuation INTEGER;
ALTER TABLE athletes ADD COLUMN IF NOT EXISTS cached_last_pulled TIMESTAMP WITH TIME ZONE;

-- Index on athlete_snapshots for the DISTINCT ON query used by precompute
CREATE INDEX IF NOT EXISTS idx_athlete_snapshots_athlete_pulled
    ON athlete_snapshots(athlete_id, pulled_at DESC);

-- Index on zoomph_posts mentions for the attributed engagement scan
CREATE INDEX IF NOT EXISTS idx_zoomph_posts_mentions
    ON zoomph_posts(mentions) WHERE mentions IS NOT NULL AND mentions != '';
