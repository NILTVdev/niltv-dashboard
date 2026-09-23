"""
Cron job: Pull daily web analytics from GA4 and Search Console.

Run:
    python -m backend.jobs.run_web_analytics

Runs daily at 4:00 AM UTC.
Delegates to the 30-day backfill to ensure GSC retroactive corrections are captured.
"""

import logging

from backend.database import SessionLocal
from backend.jobs.backfill_web_analytics import _backfill
from backend.jobs.base import run_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

BACKFILL_DAYS = 30


def _pull_web_analytics(db):
    return _backfill(db, days=BACKFILL_DAYS)


def main():
    db = SessionLocal()
    try:
        run_job("run_web_analytics", db, _pull_web_analytics, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
