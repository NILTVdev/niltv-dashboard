-- 033: Community Star review state.
--
-- What the team decides about each application, edited in the dashboard's
-- Community Star page or in the staff sheet's team columns (the export job
-- reads sheet edits back before it rewrites the tab):
--
--   applied -> shortlist -> finalist -> top5 -> winner
--           \-> disqualified
--
-- collab_accepted: the official rules count an entry once @NILTV and @NILSTAR
-- accept the collaborator invite on the applicant's post.
-- photo_url / cause / youtube_id: the finalist card on niltv.com/communitystar
-- (photo, one-line cause, round 2 video).
-- sheet_seen: the team-column values the export last wrote to the sheet, so a
-- later run can tell a sheet edit from a dashboard edit.
--
-- Applied automatically by scripts/migrate.py on deploy.

ALTER TABLE community_star_applications
    ADD COLUMN IF NOT EXISTS collab_accepted BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS stage           TEXT NOT NULL DEFAULT 'applied',
    ADD COLUMN IF NOT EXISTS notes           TEXT,
    ADD COLUMN IF NOT EXISTS photo_url       TEXT,
    ADD COLUMN IF NOT EXISTS cause           TEXT,
    ADD COLUMN IF NOT EXISTS youtube_id      TEXT,
    ADD COLUMN IF NOT EXISTS reviewed_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reviewed_by     TEXT,
    ADD COLUMN IF NOT EXISTS sheet_seen      JSONB;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_community_star_stage') THEN
        ALTER TABLE community_star_applications
            ADD CONSTRAINT ck_community_star_stage
            CHECK (stage IN ('applied', 'shortlist', 'finalist', 'top5', 'winner', 'disqualified'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_community_star_stage ON community_star_applications(season, stage);
