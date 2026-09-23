-- Expand zoomph_posts with additional analytics fields from the Zoomph API.
-- Run:  psql -h 127.0.0.1 -U niltv_user -d niltv_db -f backend/migrations/003_zoomph_expand.sql

-- Engagement breakdown
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS comment_count INTEGER;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS save_count INTEGER;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS share_count INTEGER;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS reply_count INTEGER;

-- Reach / rates
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS reach INTEGER;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS projected_impressions BIGINT;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS follower_count INTEGER;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS engagement_rate NUMERIC;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS follower_interaction_rate NUMERIC;

-- Value
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS post_value NUMERIC;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS brand_exposure_value_us NUMERIC;

-- Sentiment / context
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS sentiment TEXT;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS hashtags TEXT;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS mentions TEXT;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS language TEXT;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS partner_mention_type TEXT;

-- Video / streaming
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS view_count INTEGER;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS live_views INTEGER;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS avg_concurrent_viewers INTEGER;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS peak_live_viewer_count INTEGER;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS hours_watched BIGINT;

-- Logo AI
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS logo_total_seconds NUMERIC;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS logo_avg_size NUMERIC;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS logo_avg_clarity NUMERIC;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS logo_impressions INTEGER;
ALTER TABLE zoomph_posts ADD COLUMN IF NOT EXISTS logo_location TEXT;

-- Index on posted_at for time-range queries
CREATE INDEX IF NOT EXISTS idx_zoomph_posts_posted_at ON zoomph_posts(posted_at DESC);
