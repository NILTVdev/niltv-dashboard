-- 018: Store the IG thumbnail URL separately on brand posts.
--
-- media_url falls back to thumbnail_url when IG withholds the video URL, so
-- the poster was lost for normal videos. The app ingest bridge mirrors the
-- poster alongside the mp4 (direct-mp4 playback path), so capture it in its
-- own column; refreshed nightly like media_url (IG CDN URLs expire in hours).
--
-- Apply by hand:
--   psql -h localhost -U niltv_user -d niltv_db -f backend/migrations/018_brand_post_thumbnail.sql

ALTER TABLE brand_posts ADD COLUMN IF NOT EXISTS thumbnail_url TEXT;
