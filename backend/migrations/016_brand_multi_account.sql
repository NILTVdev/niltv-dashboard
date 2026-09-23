-- 016: Multi-account brand Instagram tracking (@niltv + @nilstar + future).
--
-- Adds an `account` discriminator to brand_snapshots / brand_posts so one
-- pipeline serves multiple owned IG accounts. Existing rows are all @niltv,
-- which the DEFAULT covers. Also adds a `shares` column to brand_posts —
-- the insights fetch now requests the `shares` metric alongside
-- views/reach/saved.

ALTER TABLE brand_snapshots ADD COLUMN IF NOT EXISTS account TEXT NOT NULL DEFAULT 'niltv';
ALTER TABLE brand_posts     ADD COLUMN IF NOT EXISTS account TEXT NOT NULL DEFAULT 'niltv';
ALTER TABLE brand_posts     ADD COLUMN IF NOT EXISTS shares  INTEGER;

CREATE INDEX IF NOT EXISTS idx_brand_snap_account  ON brand_snapshots(account);
CREATE INDEX IF NOT EXISTS idx_brand_posts_account ON brand_posts(account);
