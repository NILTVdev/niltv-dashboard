-- 026: One row per Instagram post, one post_type vocabulary, ranked view sources.
--
-- Before this migration the same post could live in both niltv_network_posts
-- and trueblue_network_posts, post_type mixed the Graph vocabulary
-- (REELS/FEED) with the Business Suite one (IG reel/IG carousel/IG image), and
-- a public play count could overwrite Graph/export views on any row it touched.
--
-- This migration:
--   1. adds niltv_network_posts.views_source and backfills it (Graph
--      vocabulary => 'graph', Business Suite vocabulary on truebluetv rows =>
--      the lowest rank, renamed 'public' in 027, everything else => 'export');
--   2. merges trueblue_network_posts into niltv_network_posts tagged
--      collab_accounts=truebluetv, export values winning over public counts,
--      and copies its snapshots across;
--   3. normalises post_type to REELS / IMAGE / CAROUSEL_ALBUM / VIDEO
--      (remaining FEED rows are upgraded by the next nightly Graph pull, which
--      now derives the format from media_type);
--   4. renames the TrueBlue network tables to *_legacy (kept as a backup,
--      nothing reads them any more).
--
-- Apply by hand (idempotent):
--   psql -h localhost -U niltv_user -d niltv_db -f backend/migrations/026_one_truth_network_posts.sql

BEGIN;

-- ── 1. views provenance ─────────────────────────────────────────────────────
ALTER TABLE niltv_network_posts ADD COLUMN IF NOT EXISTS views_source TEXT;
COMMENT ON COLUMN niltv_network_posts.views_source IS
    'Who last wrote views: graph (nightly Graph API) > export (Business Suite CSV) > scraper (public play count). A lower-ranked source never overwrites a higher one.';

UPDATE niltv_network_posts
SET views_source = CASE
        WHEN post_type IN ('REELS', 'FEED', 'IMAGE', 'CAROUSEL_ALBUM', 'VIDEO') THEN 'graph'
        WHEN collab_accounts = 'truebluetv' AND post_type LIKE 'IG %' THEN 'scraper'
        ELSE 'export'
    END
WHERE views IS NOT NULL AND views_source IS NULL;

-- ── 2. merge the TrueBlue network table into the shared table ───────────────
DO $$
BEGIN
    IF to_regclass('public.trueblue_network_posts') IS NULL THEN
        RAISE NOTICE 'trueblue_network_posts already merged — skipping';
        RETURN;
    END IF;

    -- 2a. posts only the TrueBlue table knows about
    INSERT INTO niltv_network_posts (
        post_id, account_username, account_name, description, duration_sec,
        publish_time, permalink, post_type, collab_accounts,
        views, likes, shares, comments, saves, reach, projected_reach, follows,
        ambassador_id, views_source, imported_at, updated_at)
    SELECT t.post_id, t.account_username, t.account_name, t.description, t.duration_sec,
           t.publish_time, t.permalink, t.post_type, 'truebluetv',
           t.views, t.likes, t.shares, t.comments, t.saves, t.reach, t.projected_reach, t.follows,
           t.ambassador_id, CASE WHEN t.views IS NULL THEN NULL ELSE 'export' END,
           t.imported_at, t.updated_at
    FROM trueblue_network_posts t
    WHERE NOT EXISTS (SELECT 1 FROM niltv_network_posts n
                      WHERE n.post_id = t.post_id
                         OR (t.permalink IS NOT NULL AND n.permalink = t.permalink));

    -- 2b. posts in both: union the tag, fill export-only metrics, and let the
    --     export's views replace any public count.
    UPDATE niltv_network_posts n
    SET collab_accounts = CASE
            WHEN n.collab_accounts IS NULL OR n.collab_accounts = '' THEN 'truebluetv'
            WHEN ',' || n.collab_accounts || ',' LIKE '%,truebluetv,%' THEN n.collab_accounts
            ELSE (SELECT string_agg(a, ',' ORDER BY a)
                  FROM unnest(string_to_array(n.collab_accounts || ',truebluetv', ',')) AS a)
        END,
        shares          = COALESCE(n.shares, t.shares),
        saves           = COALESCE(n.saves, t.saves),
        reach           = COALESCE(n.reach, t.reach),
        follows         = COALESCE(n.follows, t.follows),
        projected_reach = COALESCE(n.projected_reach, t.projected_reach),
        ambassador_id   = COALESCE(n.ambassador_id, t.ambassador_id),
        account_name    = COALESCE(n.account_name, t.account_name),
        duration_sec    = COALESCE(n.duration_sec, t.duration_sec),
        views           = CASE WHEN t.views IS NOT NULL AND (n.views IS NULL OR n.views_source = 'scraper')
                               THEN t.views ELSE n.views END,
        views_source    = CASE WHEN t.views IS NOT NULL AND (n.views IS NULL OR n.views_source = 'scraper')
                               THEN 'export' ELSE n.views_source END
    FROM trueblue_network_posts t
    WHERE t.post_id = n.post_id;

    -- 2c. snapshot history follows the post
    INSERT INTO niltv_network_post_snapshots (
        network_post_id, captured_at, views, likes, shares, comments, saves, reach, projected_reach, follows)
    SELECT n.id, s.captured_at, s.views, s.likes, s.shares, s.comments, s.saves, s.reach, s.projected_reach, s.follows
    FROM trueblue_network_post_snapshots s
    JOIN trueblue_network_posts t ON t.id = s.network_post_id
    JOIN niltv_network_posts n ON n.post_id = t.post_id
    WHERE NOT EXISTS (
        SELECT 1 FROM niltv_network_post_snapshots x
        WHERE x.network_post_id = n.id AND x.captured_at = s.captured_at);

    -- 2d. keep the old tables as a backup under a legacy name
    ALTER TABLE trueblue_network_post_snapshots RENAME TO trueblue_network_post_snapshots_legacy;
    ALTER TABLE trueblue_network_posts RENAME TO trueblue_network_posts_legacy;
END $$;

-- ── 3. one post_type vocabulary ─────────────────────────────────────────────
UPDATE niltv_network_posts
SET post_type = CASE lower(post_type)
        WHEN 'ig reel'      THEN 'REELS'
        WHEN 'ig reels'     THEN 'REELS'
        WHEN 'reel'         THEN 'REELS'
        WHEN 'ig carousel'  THEN 'CAROUSEL_ALBUM'
        WHEN 'carousel'     THEN 'CAROUSEL_ALBUM'
        WHEN 'ig image'     THEN 'IMAGE'
        WHEN 'image'        THEN 'IMAGE'
        WHEN 'ig video'     THEN 'VIDEO'
        ELSE post_type
    END
WHERE post_type IS NOT NULL
  AND post_type NOT IN ('REELS', 'IMAGE', 'CAROUSEL_ALBUM', 'VIDEO', 'FEED');

CREATE INDEX IF NOT EXISTS idx_niltv_network_posts_collab ON niltv_network_posts (collab_accounts);

COMMIT;
