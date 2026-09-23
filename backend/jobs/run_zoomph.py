"""
Cron job: Pull Zoomph partner mention data for Duke-owned accounts.

Runs hourly.

Each run:
  1. Fetches posts from the last 30 days (update window)
  2. Inserts new posts into zoomph_posts
  3. Updates existing posts whose engagement metrics have changed
  4. Saves a snapshot of the old metrics before each update (zoomph_post_snapshots)
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import ZoomphPost, ZoomphPostSnapshot
from backend.sources.zoomph import fetch_zoomph_posts
from backend.jobs.base import run_job, upload_to_s3
from backend.jobs.precompute import precompute_athlete_cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# How far back to re-fetch posts for metric updates
UPDATE_WINDOW_DAYS = 30

# Fields that change over time and should be tracked / updated
MUTABLE_FIELDS = [
    "engagement", "like_count", "comment_count", "save_count", "share_count",
    "reply_count", "impressions", "reach", "projected_impressions",
    "follower_count", "engagement_rate", "follower_interaction_rate",
    "brand_exposure_value", "post_value", "brand_exposure_value_us",
    "vod_views", "view_count", "live_views", "hours_watched",
]


def _post_to_dict(p) -> dict:
    """Convert a fetched ZoomphPost dataclass to a JSON-safe backup dict."""
    return {
        "post_id": p.post_id,
        "partner": p.partner,
        "platform": p.platform,
        "content_type": p.content_type,
        "author": p.author,
        "url": p.url,
        "message": p.message,
        "posted_at": p.posted_at.isoformat() if p.posted_at else None,
        "partner_mention_type": p.partner_mention_type,
        "engagement": p.engagement,
        "like_count": p.like_count,
        "comment_count": p.comment_count,
        "save_count": p.save_count,
        "share_count": p.share_count,
        "reply_count": p.reply_count,
        "impressions": p.impressions,
        "reach": p.reach,
        "projected_impressions": p.projected_impressions,
        "follower_count": p.follower_count,
        "engagement_rate": p.engagement_rate,
        "follower_interaction_rate": p.follower_interaction_rate,
        "brand_exposure_value": p.brand_exposure_value,
        "post_value": p.post_value,
        "brand_exposure_value_us": p.brand_exposure_value_us,
        "sentiment": p.sentiment,
        "hashtags": p.hashtags,
        "mentions": p.mentions,
        "language": p.language,
        "vod_views": p.vod_views,
        "view_count": p.view_count,
        "live_views": p.live_views,
        "avg_concurrent_viewers": p.avg_concurrent_viewers,
        "peak_live_viewer_count": p.peak_live_viewer_count,
        "hours_watched": p.hours_watched,
        "logo_total_seconds": p.logo_total_seconds,
        "logo_avg_size": p.logo_avg_size,
        "logo_avg_clarity": p.logo_avg_clarity,
        "logo_impressions": p.logo_impressions,
        "logo_location": p.logo_location,
    }


def _post_to_model(p, pulled_at: datetime) -> ZoomphPost:
    """Convert a fetched ZoomphPost dataclass to a DB model instance."""
    return ZoomphPost(
        pulled_at=pulled_at,
        post_id=p.post_id,
        partner=p.partner,
        platform=p.platform,
        content_type=p.content_type,
        author=p.author,
        url=p.url,
        message=p.message,
        posted_at=p.posted_at,
        partner_mention_type=p.partner_mention_type,
        engagement=p.engagement,
        like_count=p.like_count,
        comment_count=p.comment_count,
        save_count=p.save_count,
        share_count=p.share_count,
        reply_count=p.reply_count,
        impressions=p.impressions,
        reach=p.reach,
        projected_impressions=p.projected_impressions,
        follower_count=p.follower_count,
        engagement_rate=p.engagement_rate,
        follower_interaction_rate=p.follower_interaction_rate,
        brand_exposure_value=p.brand_exposure_value,
        post_value=p.post_value,
        brand_exposure_value_us=p.brand_exposure_value_us,
        sentiment=p.sentiment,
        hashtags=p.hashtags,
        mentions=p.mentions,
        language=p.language,
        vod_views=p.vod_views,
        view_count=p.view_count,
        live_views=p.live_views,
        avg_concurrent_viewers=p.avg_concurrent_viewers,
        peak_live_viewer_count=p.peak_live_viewer_count,
        hours_watched=p.hours_watched,
        logo_total_seconds=p.logo_total_seconds,
        logo_avg_size=p.logo_avg_size,
        logo_avg_clarity=p.logo_avg_clarity,
        logo_impressions=p.logo_impressions,
        logo_location=p.logo_location,
    )


def _snapshot_from_db_row(db_row: ZoomphPost, captured_at: datetime) -> ZoomphPostSnapshot:
    """Capture the current DB values as a snapshot before updating."""
    return ZoomphPostSnapshot(
        zoomph_post_id=db_row.id,
        captured_at=captured_at,
        engagement=db_row.engagement,
        like_count=db_row.like_count,
        comment_count=db_row.comment_count,
        save_count=db_row.save_count,
        share_count=db_row.share_count,
        reply_count=db_row.reply_count,
        impressions=db_row.impressions,
        reach=db_row.reach,
        projected_impressions=db_row.projected_impressions,
        follower_count=db_row.follower_count,
        engagement_rate=db_row.engagement_rate,
        follower_interaction_rate=db_row.follower_interaction_rate,
        brand_exposure_value=db_row.brand_exposure_value,
        post_value=db_row.post_value,
        brand_exposure_value_us=db_row.brand_exposure_value_us,
        vod_views=db_row.vod_views,
        view_count=db_row.view_count,
        live_views=db_row.live_views,
        hours_watched=db_row.hours_watched,
    )


def _has_changes(db_row: ZoomphPost, fetched) -> bool:
    """Check if any mutable metric differs between the DB row and fetched data."""
    for field in MUTABLE_FIELDS:
        db_val = getattr(db_row, field, None)
        new_val = getattr(fetched, field, None)
        # Only count as changed if the new value is not None
        # (avoid overwriting good data with nulls from incomplete reports)
        if new_val is not None and db_val != new_val:
            return True
    return False


def _update_db_row(db_row: ZoomphPost, fetched, updated_at: datetime) -> None:
    """Apply updated metrics from fetched data onto the existing DB row."""
    for field in MUTABLE_FIELDS:
        new_val = getattr(fetched, field, None)
        if new_val is not None:
            setattr(db_row, field, new_val)
    # Also update fields that may have been null on first pull
    if db_row.posted_at is None and fetched.posted_at is not None:
        db_row.posted_at = fetched.posted_at
    if db_row.author is None and fetched.author is not None:
        db_row.author = fetched.author
    if db_row.sentiment is None and fetched.sentiment is not None:
        db_row.sentiment = fetched.sentiment
    db_row.updated_at = updated_at


def upsert_zoomph_posts(db: Session, posts: list, pulled_at: datetime) -> tuple[int, int]:
    """
    Insert new posts and update existing ones. Returns (inserted, updated).

    For updated posts, saves a snapshot of the old metrics before overwriting.
    Shared by both the hourly cron and the backfill job.
    """
    if not posts:
        return 0, 0

    # Load existing DB rows for matching post_ids
    fetched_ids = [p.post_id for p in posts]
    existing_rows = (
        db.query(ZoomphPost)
        .filter(ZoomphPost.post_id.in_(fetched_ids))
        .all()
    )
    existing_map: dict[str, ZoomphPost] = {row.post_id: row for row in existing_rows}

    records_inserted = 0
    records_updated = 0
    backup_data = []
    batch_size = 500

    for p in posts:
        db_row = existing_map.get(p.post_id)

        if db_row is None:
            # New post — insert
            db.add(_post_to_model(p, pulled_at))
            records_inserted += 1
            backup_data.append(_post_to_dict(p))

        elif _has_changes(db_row, p):
            # Existing post with changed metrics — snapshot then update
            db.add(_snapshot_from_db_row(db_row, pulled_at))
            _update_db_row(db_row, p, pulled_at)
            records_updated += 1
            backup_data.append(_post_to_dict(p))

        # Flush in batches to keep memory bounded
        total = records_inserted + records_updated
        if total > 0 and total % batch_size == 0:
            db.flush()
            logger.info(f"Flushed {total} records so far ({records_inserted} new, {records_updated} updated)")

    db.commit()

    if backup_data:
        ts = pulled_at.strftime("%Y-%m-%dT%H-%M-%S")
        upload_to_s3(backup_data, f"backups/zoomph/{ts}.json")

    return records_inserted, records_updated


def _pull_zoomph(db: Session) -> int:
    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(days=UPDATE_WINDOW_DAYS)
    logger.info(f"Fetching Zoomph posts from {since:%Y-%m-%d} to {now:%Y-%m-%d} ({UPDATE_WINDOW_DAYS}-day window)")

    posts = fetch_zoomph_posts(since=since, until=now)
    if not posts:
        logger.info("No Zoomph posts found.")
        return 0

    inserted, updated = upsert_zoomph_posts(db, posts, now)
    logger.info(f"Done: {inserted} inserted, {updated} updated")
    return inserted + updated


def main():
    db = SessionLocal()
    try:
        run_job("run_zoomph", db, _pull_zoomph, db)
        logger.info("Running athlete cache precompute...")
        precompute_athlete_cache(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
