-- 024: Multi-platform + provenance on ambassador snapshots.
--
-- TikTok/YouTube have no pull pipeline — those numbers arrive from the
-- self-reported master sheet (scripts/import_ambassador_sheet.py) and only
-- move on re-import. The source tag keeps survey numbers ('reported') from
-- masquerading as API-pulled ones ('business_discovery') in trendlines.
--
-- Apply by hand:
--   psql -h localhost -U niltv_user -d niltv_db -f backend/migrations/024_ambassador_snapshot_platforms.sql

ALTER TABLE ambassador_snapshots ADD COLUMN IF NOT EXISTS tiktok_followers    INTEGER;
ALTER TABLE ambassador_snapshots ADD COLUMN IF NOT EXISTS youtube_subscribers INTEGER;
ALTER TABLE ambassador_snapshots ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'business_discovery';
