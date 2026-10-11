-- 029: One row per onboarding reconcile run (nightly job or the dashboard's
-- "Refresh all" button).
--
-- The run re-checks every open application against DocuSign and Stripe, so a
-- missed webhook cannot leave a row stuck. stats holds the counts plus the
-- list of rows that changed; per-row changes are also in application_events.
--
-- Applied automatically by scripts/migrate.py on deploy.

CREATE TABLE IF NOT EXISTS reconcile_runs (
    id            SERIAL PRIMARY KEY,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    trigger       TEXT NOT NULL,          -- nightly | staff
    triggered_by  TEXT,
    stats         JSONB,
    error         TEXT
);

CREATE INDEX IF NOT EXISTS idx_reconcile_runs_started ON reconcile_runs(started_at DESC);
