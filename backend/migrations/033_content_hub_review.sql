-- 033: Content Hub: ask format and tags, and staff approval of submissions.
--
-- Staff set a format when posting an ask (a reel, a photo set, a podcast
-- clip) and tag it so athletes can filter the hub. A submitted claim is
-- then approved by staff; approved claims are what admin later pays out.
--
--   * claim status gains 'approved' (claimed -> submitted -> approved);
--   * reviewed_by points at the dashboard account that approved it and is
--     cleared, not cascaded, if that account is removed.
--
-- Applied automatically by scripts/migrate.py on deploy.

ALTER TABLE hub_asks ADD COLUMN IF NOT EXISTS format TEXT;
ALTER TABLE hub_asks ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_hub_asks_tags ON hub_asks USING GIN (tags);

ALTER TABLE hub_claims DROP CONSTRAINT IF EXISTS hub_claims_status_check;
ALTER TABLE hub_claims ADD CONSTRAINT hub_claims_status_check
    CHECK (status IN ('claimed', 'submitted', 'approved', 'released'));

ALTER TABLE hub_claims ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
ALTER TABLE hub_claims ADD COLUMN IF NOT EXISTS reviewed_by INTEGER
    REFERENCES dashboard_users(id) ON DELETE SET NULL;
