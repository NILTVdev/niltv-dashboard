-- 023: Roster fields on ambassadors + nullable handle.
--
-- The Campus Ambassadors master sheet keys on name + school and has no IG
-- handles, so ig_username becomes nullable: sheet-only ambassadors exist in
-- the registry before their handle is known (attribution and enrichment
-- already skip handleless rows; filling the handle later via the admin
-- update endpoint attributes their posts immediately). The UNIQUE
-- constraint stays — Postgres allows any number of NULLs under it.
--
-- school (their university, free text from the sheet) is deliberately NOT
-- campus (our channel node, e.g. 'chapelhilltv' -> unc). cohort tags the
-- survey round (e.g. 'F26') so future lists coexist instead of overwriting.
-- profile_pic_url/website come from Business Discovery and are refreshed
-- nightly (IG CDN URLs expire).
--
-- Apply by hand:
--   psql -h localhost -U niltv_user -d niltv_db -f backend/migrations/023_ambassador_roster_fields.sql

ALTER TABLE ambassadors ALTER COLUMN ig_username DROP NOT NULL;

ALTER TABLE ambassadors ADD COLUMN IF NOT EXISTS school          TEXT;
ALTER TABLE ambassadors ADD COLUMN IF NOT EXISTS sport           TEXT;
ALTER TABLE ambassadors ADD COLUMN IF NOT EXISTS year            TEXT;
ALTER TABLE ambassadors ADD COLUMN IF NOT EXISTS gender          TEXT;   -- 'M' | 'F' as reported
ALTER TABLE ambassadors ADD COLUMN IF NOT EXISTS cohort          TEXT;   -- e.g. 'F26'
ALTER TABLE ambassadors ADD COLUMN IF NOT EXISTS profile_pic_url TEXT;
ALTER TABLE ambassadors ADD COLUMN IF NOT EXISTS website         TEXT;
