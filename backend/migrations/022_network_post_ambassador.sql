-- 022: Ambassador attribution on network post tables.
--
-- Stamped by the attribution pass (backend/jobs/ambassadors.py) after each
-- network upsert: any post whose lowercased account_username matches a
-- non-removed ambassador gets the FK. The FK survives IG handle renames,
-- which the raw account_username string would not. SET NULL on delete so
-- removing an ambassador row never touches post data.
--
-- Apply by hand:
--   psql -h localhost -U niltv_user -d niltv_db -f backend/migrations/022_network_post_ambassador.sql

ALTER TABLE niltv_network_posts
    ADD COLUMN IF NOT EXISTS ambassador_id INTEGER REFERENCES ambassadors(id) ON DELETE SET NULL;

ALTER TABLE trueblue_network_posts
    ADD COLUMN IF NOT EXISTS ambassador_id INTEGER REFERENCES ambassadors(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_niltv_network_posts_ambassador
    ON niltv_network_posts(ambassador_id);

CREATE INDEX IF NOT EXISTS idx_network_posts_ambassador
    ON trueblue_network_posts(ambassador_id);
