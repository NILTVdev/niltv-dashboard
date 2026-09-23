-- Add a `site` discriminator to the web-analytics tables so the dashboard can
-- track multiple properties (truebluetv.com + niltv.com) in the same tables.
-- Existing rows belong to truebluetv, so default to 'truebluetv'.
--
-- Run:  psql -h 127.0.0.1 -U niltv_user -d niltv_db -f backend/migrations/014_web_analytics_site.sql

ALTER TABLE ga4_daily_snapshots ADD COLUMN IF NOT EXISTS site TEXT NOT NULL DEFAULT 'truebluetv';
ALTER TABLE gsc_daily_totals    ADD COLUMN IF NOT EXISTS site TEXT NOT NULL DEFAULT 'truebluetv';
ALTER TABLE gsc_query_snapshots ADD COLUMN IF NOT EXISTS site TEXT NOT NULL DEFAULT 'truebluetv';
ALTER TABLE gsc_page_snapshots  ADD COLUMN IF NOT EXISTS site TEXT NOT NULL DEFAULT 'truebluetv';

-- Composite indexes for the common (site, date) filter
CREATE INDEX IF NOT EXISTS idx_ga4_site_date       ON ga4_daily_snapshots(site, date DESC);
CREATE INDEX IF NOT EXISTS idx_gsc_daily_site_date ON gsc_daily_totals(site, date DESC);
CREATE INDEX IF NOT EXISTS idx_gsc_query_site_date ON gsc_query_snapshots(site, date DESC);
CREATE INDEX IF NOT EXISTS idx_gsc_page_site_date  ON gsc_page_snapshots(site, date DESC);
