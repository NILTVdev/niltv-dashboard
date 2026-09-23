"""
One-off backfill: Pull historical Zoomph partner mention data.

Usage:
    python -m backend.jobs.backfill_zoomph
    python -m backend.jobs.backfill_zoomph --start-date 2024-01-01
    python -m backend.jobs.backfill_zoomph --start-date 2024-01-01 --end-date 2025-01-01

Pulls in 30-day chunks to avoid oversized API responses (Zoomph has no
pagination). Uses the same upsert logic as the hourly cron — inserts new
posts and updates existing ones with changed metrics.
"""

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.sources.zoomph import fetch_zoomph_posts
from backend.jobs.run_zoomph import upsert_zoomph_posts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

CHUNK_DAYS = 30


def _backfill(db: Session, start_date: datetime, end_date: datetime) -> int:
    pulled_at = datetime.now(tz=timezone.utc)
    total_inserted = 0
    total_updated = 0

    chunk_start = start_date
    while chunk_start < end_date:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), end_date)
        logger.info(f"=== Chunk: {chunk_start:%Y-%m-%d} → {chunk_end:%Y-%m-%d} ===")

        try:
            posts = fetch_zoomph_posts(since=chunk_start, until=chunk_end)
            logger.info(f"Fetched {len(posts)} posts from Zoomph")

            inserted, updated = upsert_zoomph_posts(db, posts, pulled_at)
            total_inserted += inserted
            total_updated += updated

            logger.info(f"Chunk done: {inserted} inserted, {updated} updated")

        except Exception as exc:
            db.rollback()
            logger.error(f"Chunk {chunk_start:%Y-%m-%d} → {chunk_end:%Y-%m-%d} failed: {exc}")

        # Wait between chunks to respect Zoomph rate limits
        chunk_start = chunk_end
        if chunk_start < end_date:
            logger.info("Waiting 30s before next chunk...")
            time.sleep(30)

    logger.info(
        f"\nBackfill complete — {total_inserted} inserted, {total_updated} updated"
    )
    return total_inserted + total_updated


def main():
    parser = argparse.ArgumentParser(description="Backfill historical Zoomph data")
    parser.add_argument(
        "--start-date",
        type=str,
        default="2024-01-01",
        help="Start date YYYY-MM-DD (default: 2024-01-01)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date YYYY-MM-DD (default: today)",
    )
    args = parser.parse_args()

    start = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if args.end_date:
        end = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        end = datetime.now(tz=timezone.utc)

    logger.info(f"Backfilling Zoomph data from {start:%Y-%m-%d} to {end:%Y-%m-%d}")

    db = SessionLocal()
    try:
        _backfill(db, start, end)
    finally:
        db.close()


if __name__ == "__main__":
    main()
