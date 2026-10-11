"""Nightly onboarding reconcile: re-check every open application against
DocuSign and Stripe so a missed webhook cannot leave a row stuck.

The logic lives in ``backend.onboarding.reconcile`` (shared with the
dashboard's "Refresh all" button). Each run is a row in ``reconcile_runs``.
The job fails (SNS alert) when any row errored or the run crashed.

Schedule: daily 06:30 UTC.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.jobs.base import run_job
from backend.onboarding import reconcile


def reconcile_applications(db: Session) -> int:
    if reconcile.running(db):
        return 0  # a staff-triggered run is in progress; it covers tonight
    run = reconcile.execute(db, reconcile.start(db, "nightly"))
    if run.error:
        raise RuntimeError(f"reconcile run {run.id}: {run.error}")
    return (run.stats or {}).get("changed", 0)


def main():
    db = SessionLocal()
    try:
        run_job("reconcile_applications", db, reconcile_applications, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
