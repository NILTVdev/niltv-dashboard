"""
Cron job: Pull public YouTube channel and video counts (Data API v3).

Run:
    scripts/run_job.sh backend.jobs.run_youtube

Runs daily at 5:25 AM UTC.
For each channel in YOUTUBE_CHANNEL_IDS: channel totals (subscribers, total
views, video count) into youtube_channel_snapshots, every upload into
youtube_videos with its current counts, and one youtube_video_snapshots row
per video. Snapshots are one row per UTC day, so a re-run the same day
overwrites that day instead of adding a row.

Needs only YOUTUBE_API_KEY. Without it the job logs "not configured" and
exits 0. Quota: about 1 + 2 * ceil(uploads / 50) units per channel.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import SessionLocal
from backend.jobs.base import run_job, upload_to_s3
from backend.models import YoutubeChannel, YoutubeChannelSnapshot, YoutubeVideo, YoutubeVideoSnapshot
from backend.sources.youtube import (
    Calls, ChannelData, VideoData, fetch_channels, fetch_upload_ids, fetch_videos,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def upsert_channel(db: Session, ch: ChannelData, now: datetime) -> None:
    values = dict(
        channel_id=ch.channel_id, title=ch.title, handle=ch.handle,
        uploads_playlist_id=ch.uploads_playlist_id, thumbnail_url=ch.thumbnail_url, updated_at=now,
    )
    stmt = insert(YoutubeChannel).values(**values)
    db.execute(stmt.on_conflict_do_update(
        index_elements=[YoutubeChannel.channel_id],
        set_={k: stmt.excluded[k] for k in values if k != "channel_id"},
    ))


def upsert_channel_snapshot(db: Session, ch: ChannelData, now: datetime) -> None:
    stmt = insert(YoutubeChannelSnapshot).values(
        channel_id=ch.channel_id, day=now.date(), pulled_at=now,
        subscribers=ch.subscribers, total_views=ch.total_views, video_count=ch.video_count,
    )
    db.execute(stmt.on_conflict_do_update(
        constraint="uq_youtube_channel_snapshot_day",
        set_={k: stmt.excluded[k] for k in ("pulled_at", "subscribers", "total_views", "video_count")},
    ))


def upsert_videos(db: Session, channel_id: str, videos: list[VideoData], now: datetime) -> int:
    """Upsert each video and its snapshot for today. Returns snapshot rows written."""
    day = now.date()
    for v in videos:
        values = dict(
            video_id=v.video_id, channel_id=channel_id, title=v.title,
            published_at=v.published_at, duration_sec=v.duration_sec, is_short=v.is_short,
            thumbnail_url=v.thumbnail_url, views=v.views, likes=v.likes, comments=v.comments,
            updated_at=now,
        )
        stmt = insert(YoutubeVideo).values(**values)
        db.execute(stmt.on_conflict_do_update(
            index_elements=[YoutubeVideo.video_id],
            set_={k: stmt.excluded[k] for k in values if k != "video_id"},
        ))
        snap = insert(YoutubeVideoSnapshot).values(
            video_id=v.video_id, day=day, views=v.views, likes=v.likes, comments=v.comments)
        db.execute(snap.on_conflict_do_update(
            constraint="uq_youtube_video_snapshot_day",
            set_={k: snap.excluded[k] for k in ("views", "likes", "comments")},
        ))
    return len(videos)


def pull_youtube(db: Session, client: Optional[httpx.Client] = None,
                 now: Optional[datetime] = None) -> int:
    settings = get_settings()
    if not settings.youtube_configured:
        logger.info("YouTube not configured: YOUTUBE_API_KEY is empty. Nothing pulled.")
        return 0
    channel_ids = settings.youtube_channel_id_list()

    now = now or datetime.now(timezone.utc)
    key = settings.youtube_api_key.strip()
    calls = Calls()
    own_client = client is None
    client = client or httpx.Client()
    written = 0
    backup: dict = {"pulled_at": now.isoformat(), "channels": []}
    try:
        channels = fetch_channels(client, key, channel_ids, calls)
        missing = set(channel_ids) - {c.channel_id for c in channels}
        if missing:
            logger.warning(f"YouTube channels not found: {', '.join(sorted(missing))}")
        for ch in channels:
            upsert_channel(db, ch, now)
            upsert_channel_snapshot(db, ch, now)
            ids = fetch_upload_ids(client, key, ch.uploads_playlist_id, calls) if ch.uploads_playlist_id else []
            videos = fetch_videos(client, key, ids, calls) if ids else []
            written += 1 + upsert_videos(db, ch.channel_id, videos, now)
            # One transaction per channel: a later channel failing keeps this one.
            db.commit()
            logger.info(
                f"YouTube {ch.handle or ch.channel_id}: subscribers={ch.subscribers} "
                f"views={ch.total_views} uploads listed={len(ids)} videos saved={len(videos)}")
            backup["channels"].append({
                "channel": vars(ch),
                "videos": [vars(v) for v in videos],
            })
    finally:
        if own_client:
            client.close()
    logger.info(f"YouTube pull used {calls.count} API calls (about {calls.count} quota units)")
    upload_to_s3(backup, f"youtube/{now:%Y-%m-%d}.json")
    return written


def main():
    db = SessionLocal()
    try:
        run_job("run_youtube", db, pull_youtube, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
