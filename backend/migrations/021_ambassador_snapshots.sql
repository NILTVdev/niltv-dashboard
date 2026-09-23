-- 021: Point-in-time profile snapshots for ambassadors.
--
-- Written by the enrichment pass in backend.jobs.run_instagram (Business
-- Discovery, profile fields only). Ambassadors linked to an athletes row are
-- skipped there — their trendline already lives in athlete_snapshots.
--
-- Apply by hand:
--   psql -h localhost -U niltv_user -d niltv_db -f backend/migrations/021_ambassador_snapshots.sql

CREATE TABLE IF NOT EXISTS ambassador_snapshots (
    id            SERIAL PRIMARY KEY,
    ambassador_id INTEGER NOT NULL REFERENCES ambassadors(id) ON DELETE CASCADE,
    pulled_at     TIMESTAMPTZ DEFAULT now(),
    followers     INTEGER,
    post_count    INTEGER,
    bio           TEXT
);

CREATE INDEX IF NOT EXISTS idx_ambassador_snap_amb_pulled
    ON ambassador_snapshots(ambassador_id, pulled_at);
