"""
One-off backfill: Pull historical GA4 + GSC data (default 90 days).

Pulls every configured site (truebluetv.com, and niltv.com when its env vars
are set) and tags each row with its `site`.

Usage:
    python -m backend.jobs.backfill_web_analytics          # 90 days
    python -m backend.jobs.backfill_web_analytics --days 180
"""

import argparse
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import SessionLocal
from backend.models import (
    GA4DailySnapshot, GSCDailyTotal, GSCQuerySnapshot, GSCPageSnapshot,
)
from backend.sources.ga4 import fetch_ga4_daily
from backend.sources.gsc import (
    fetch_gsc_daily_totals, fetch_gsc_by_query, fetch_gsc_by_page,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

CHUNK_DAYS = 30


def _dt(d) -> datetime:
    return datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)


def _backfill(db: Session, days: int) -> int:
    """Backfill every configured site. Returns total rows inserted."""
    pulled_at = datetime.now(tz=timezone.utc)
    today = pulled_at.date()
    end = today - timedelta(days=1)
    start = end - timedelta(days=days - 1)

    total_inserted = 0
    for target in get_settings().web_analytics_targets():
        logger.info(f"########## Site: {target['site']} ##########")
        total_inserted += _backfill_site(
            db,
            site=target["site"],
            ga4_property=target["ga4_property_id"],
            gsc_url=target["gsc_site_url"],
            start=start,
            end=end,
            pulled_at=pulled_at,
        )

    logger.info(f"Backfill complete — {total_inserted} total records inserted")
    return total_inserted


def _backfill_site(db, site, ga4_property, gsc_url, start, end, pulled_at) -> int:
    """Backfill a single site (chunked by CHUNK_DAYS)."""
    total_inserted = 0
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS - 1), end)
        s_str = chunk_start.isoformat()
        e_str = chunk_end.isoformat()
        start_dt = _dt(chunk_start)
        end_dt = _dt(chunk_end)

        logger.info(f"=== [{site}] Chunk: {s_str} → {e_str} ===")

        # ── GA4 ──
        if ga4_property:
            try:
                logger.info(f"[{site}] Pulling GA4 {s_str} to {e_str}...")
                ga4_rows = fetch_ga4_daily(s_str, e_str, property_id=ga4_property)

                db.query(GA4DailySnapshot).filter(
                    GA4DailySnapshot.site == site,
                    GA4DailySnapshot.date >= start_dt,
                    GA4DailySnapshot.date <= end_dt,
                ).delete(synchronize_session=False)

                for row in ga4_rows:
                    db.add(GA4DailySnapshot(
                        site=site,
                        date=_dt(row.date),
                        pulled_at=pulled_at,
                        sessions=row.sessions,
                        total_users=row.total_users,
                        pageviews=row.pageviews,
                        bounce_rate=row.bounce_rate,
                        engagement_rate=row.engagement_rate,
                        source=row.source,
                        medium=row.medium,
                    ))
                    total_inserted += 1
                db.commit()
                logger.info(f"[{site}] GA4: inserted {len(ga4_rows)} rows for this chunk")
            except Exception as e:
                db.rollback()
                logger.error(f"[{site}] GA4 chunk failed: {e}")

        # ── GSC (totals, queries, pages) ──
        if gsc_url:
            try:
                logger.info(f"[{site}] Pulling GSC daily totals {s_str} to {e_str}...")
                totals = fetch_gsc_daily_totals(s_str, e_str, site_url=gsc_url)

                db.query(GSCDailyTotal).filter(
                    GSCDailyTotal.site == site,
                    GSCDailyTotal.date >= start_dt,
                    GSCDailyTotal.date <= end_dt,
                ).delete(synchronize_session=False)

                for row in totals:
                    db.add(GSCDailyTotal(
                        site=site, date=_dt(row.date), pulled_at=pulled_at,
                        clicks=row.clicks, impressions=row.impressions,
                        ctr=row.ctr, position=row.position,
                    ))
                    total_inserted += 1
                db.commit()
                logger.info(f"[{site}] GSC totals: inserted {len(totals)} rows")
            except Exception as e:
                db.rollback()
                logger.error(f"[{site}] GSC totals chunk failed: {e}")

            try:
                logger.info(f"[{site}] Pulling GSC queries {s_str} to {e_str}...")
                queries = fetch_gsc_by_query(s_str, e_str, site_url=gsc_url)

                db.query(GSCQuerySnapshot).filter(
                    GSCQuerySnapshot.site == site,
                    GSCQuerySnapshot.date >= start_dt,
                    GSCQuerySnapshot.date <= end_dt,
                ).delete(synchronize_session=False)

                for row in queries:
                    db.add(GSCQuerySnapshot(
                        site=site, date=_dt(row.date), pulled_at=pulled_at,
                        query=row.query, clicks=row.clicks,
                        impressions=row.impressions, ctr=row.ctr, position=row.position,
                    ))
                    total_inserted += 1
                db.commit()
                logger.info(f"[{site}] GSC queries: inserted {len(queries)} rows")
            except Exception as e:
                db.rollback()
                logger.error(f"[{site}] GSC queries chunk failed: {e}")

            try:
                logger.info(f"[{site}] Pulling GSC pages {s_str} to {e_str}...")
                pages = fetch_gsc_by_page(s_str, e_str, site_url=gsc_url)

                db.query(GSCPageSnapshot).filter(
                    GSCPageSnapshot.site == site,
                    GSCPageSnapshot.date >= start_dt,
                    GSCPageSnapshot.date <= end_dt,
                ).delete(synchronize_session=False)

                for row in pages:
                    db.add(GSCPageSnapshot(
                        site=site, date=_dt(row.date), pulled_at=pulled_at,
                        page=row.page, clicks=row.clicks,
                        impressions=row.impressions, ctr=row.ctr, position=row.position,
                    ))
                    total_inserted += 1
                db.commit()
                logger.info(f"[{site}] GSC pages: inserted {len(pages)} rows")
            except Exception as e:
                db.rollback()
                logger.error(f"[{site}] GSC pages chunk failed: {e}")

        chunk_start = chunk_end + timedelta(days=1)

    return total_inserted


def main():
    parser = argparse.ArgumentParser(description="Backfill web analytics data")
    parser.add_argument("--days", type=int, default=90, help="Number of days to backfill (default 90)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        _backfill(db, args.days)
    finally:
        db.close()


if __name__ == "__main__":
    main()
