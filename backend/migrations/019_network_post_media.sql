-- 019: Media URLs + collab-account attribution on network posts.
--
-- Campus channel Page tokens expose media_url/thumbnail_url on the
-- collaborative_media edge, which is where athlete collab posts live — the
-- app ingest bridge mirrors these into the app. collab_accounts records
-- which of OUR accounts' edges surfaced the post (comma list, e.g.
-- "niltv,starkvilletv") so the app can place the clip in the right channel.
-- URLs are refreshed on every pull (IG CDN URLs expire in hours).
--
-- Apply by hand:
--   psql -h localhost -U niltv_user -d niltv_db -f backend/migrations/019_network_post_media.sql

ALTER TABLE niltv_network_posts ADD COLUMN IF NOT EXISTS media_url TEXT;
ALTER TABLE niltv_network_posts ADD COLUMN IF NOT EXISTS thumbnail_url TEXT;
ALTER TABLE niltv_network_posts ADD COLUMN IF NOT EXISTS collab_accounts TEXT;
