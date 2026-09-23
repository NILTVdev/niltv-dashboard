-- Add projected_reach column to network posts and snapshots.
-- Only populated for posts MISSING real reach (NULL or 0).
-- Posts with actual reach leave projected_reach as NULL.

ALTER TABLE trueblue_network_posts
  ADD COLUMN IF NOT EXISTS projected_reach INTEGER;

ALTER TABLE trueblue_network_post_snapshots
  ADD COLUMN IF NOT EXISTS projected_reach INTEGER;

-- Backfill: compute avg reach/views ratio, then populate projected_reach
-- ONLY for posts/snapshots where reach is NULL or 0.
DO $$
DECLARE
  avg_ratio FLOAT;
BEGIN
  SELECT AVG(reach::float / NULLIF(views, 0))
    INTO avg_ratio
    FROM trueblue_network_posts
    WHERE reach IS NOT NULL AND reach > 0 AND views > 0;

  IF avg_ratio IS NOT NULL THEN
    -- Posts missing reach but having views
    UPDATE trueblue_network_posts
      SET projected_reach = ROUND(views * avg_ratio)
      WHERE (reach IS NULL OR reach = 0) AND views > 0;

    -- Snapshots missing reach but having views
    UPDATE trueblue_network_post_snapshots
      SET projected_reach = ROUND(views * avg_ratio)
      WHERE (reach IS NULL OR reach = 0) AND views > 0;
  END IF;
END $$;
