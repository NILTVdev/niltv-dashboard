-- 015: Add a `views` column to brand_posts (+ backfill the brand table creation).
--
-- `views` is Instagram's universal consumption metric (Graph API v22+), available
-- for FEED (image/carousel), VIDEO, and Reels via the insights endpoint. The old
-- `impressions` metric was deprecated for media created on/after 2024-07-02, so we
-- now capture real views here instead of relying on impressions.
--
-- NOTE: brand_snapshots / brand_posts were originally created by hand in prod and
-- never had a creating migration, so a from-scratch migration run had no table to
-- ALTER. This migration is therefore self-contained: it CREATEs the brand tables
-- IF NOT EXISTS (no-op in prod) and then ensures the `views` column exists (the
-- ALTER covers prod, where the tables predate this column).

CREATE TABLE IF NOT EXISTS brand_snapshots (
    id          SERIAL PRIMARY KEY,
    pulled_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    username    TEXT,
    followers   INTEGER,
    post_count  INTEGER,
    bio         TEXT
);

CREATE INDEX IF NOT EXISTS idx_brand_snap_pulled ON brand_snapshots(pulled_at);

CREATE TABLE IF NOT EXISTS brand_posts (
    id            SERIAL PRIMARY KEY,
    ig_post_id    TEXT UNIQUE NOT NULL,
    posted_at     TIMESTAMPTZ,
    media_type    TEXT,
    caption       TEXT,
    like_count    INTEGER,
    comment_count INTEGER,
    permalink     TEXT,
    media_url     TEXT,
    impressions   INTEGER,
    reach         INTEGER,
    saves         INTEGER,
    views         INTEGER,
    pulled_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_brand_posts_posted ON brand_posts(posted_at);

-- For existing prod tables created before the views column existed:
ALTER TABLE brand_posts ADD COLUMN IF NOT EXISTS views INTEGER;
