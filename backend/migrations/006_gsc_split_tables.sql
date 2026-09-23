-- Split GSC data into 3 tables for accurate reporting.
-- The old gsc_daily_snapshots used (date, query, page) dimensions which caused
-- ~50% data loss from Google's anonymization. New structure:
--   gsc_daily_totals   — accurate daily aggregates (date-only dimension)
--   gsc_query_snapshots — per-query breakdown (subject to anonymization)
--   gsc_page_snapshots  — per-page breakdown (subject to anonymization)
--
-- Run:  psql -h 127.0.0.1 -U niltv_user -d niltv_db -f backend/migrations/006_gsc_split_tables.sql

-- Accurate daily totals (no dimensional anonymization)
CREATE TABLE IF NOT EXISTS gsc_daily_totals (
    id SERIAL PRIMARY KEY,
    date TIMESTAMPTZ NOT NULL,
    pulled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    clicks INTEGER,
    impressions INTEGER,
    ctr NUMERIC,
    position NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_gsc_daily_totals_date ON gsc_daily_totals(date DESC);

-- Per-query metrics
CREATE TABLE IF NOT EXISTS gsc_query_snapshots (
    id SERIAL PRIMARY KEY,
    date TIMESTAMPTZ NOT NULL,
    pulled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    query TEXT NOT NULL,
    clicks INTEGER,
    impressions INTEGER,
    ctr NUMERIC,
    position NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_gsc_query_snapshots_date ON gsc_query_snapshots(date DESC);

-- Per-page metrics
CREATE TABLE IF NOT EXISTS gsc_page_snapshots (
    id SERIAL PRIMARY KEY,
    date TIMESTAMPTZ NOT NULL,
    pulled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    page TEXT NOT NULL,
    clicks INTEGER,
    impressions INTEGER,
    ctr NUMERIC,
    position NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_gsc_page_snapshots_date ON gsc_page_snapshots(date DESC);
