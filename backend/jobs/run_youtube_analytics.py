"""
Cron job: Pull YouTube Analytics (watch time, retention) for the owner's channel.

Run:
    scripts/run_job.sh backend.jobs.run_youtube_analytics

Runs daily at 5:40 AM UTC, after run_youtube.
Needs the channel owner's one-time OAuth consent: YOUTUBE_OAUTH_CLIENT_ID,
YOUTUBE_OAUTH_CLIENT_SECRET and YOUTUBE_OAUTH_REFRESH_TOKEN (the refresh token
comes from scripts/youtube_oauth.py). With any of them empty the job logs
"not connected" and exits 0.

Two reports.query calls with ids=channel==MINE:
  * daily channel metrics for the last 30 days into youtube_daily_analytics.
    Each night re-pulls the whole window and upserts, because YouTube revises
    recent days and reports with a lag of about two days.
  * per-video 28-day totals (dimensions=video, sort=-views, top 200) into
    youtube_video_analytics with period_end = the window's last day.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import SessionLocal
from backend.jobs.base import run_job, upload_to_s3
from backend.models import YoutubeChannel, YoutubeDailyAnalytics, YoutubeVideoAnalytics
from backend.sources.youtube import Calls, fetch_my_channel, query_report, refresh_access_token

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

DAILY_WINDOW_DAYS = 30
VIDEO_WINDOW_DAYS = 28
TOP_VIDEOS = 200
DAILY_METRICS = ("views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                 "subscribersGained,subscribersLost")
VIDEO_METRICS = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage"


def _int(v) -> Optional[int]:
    return int(round(float(v))) if v is not None else None


def _float(v) -> Optional[float]:
    return round(float(v), 2) if v is not None else None


def upsert_daily(db: Session, channel_id: str, rows: list[dict], now: datetime) -> int:
    for r in rows:
        stmt = insert(YoutubeDailyAnalytics).values(
            channel_id=channel_id,
            day=date.fromisoformat(r["day"]),
            views=_int(r.get("views")),
            estimated_minutes_watched=_int(r.get("estimatedMinutesWatched")),
            average_view_duration_sec=_int(r.get("averageViewDuration")),
            average_view_percentage=_float(r.get("averageViewPercentage")),
            subscribers_gained=_int(r.get("subscribersGained")),
            subscribers_lost=_int(r.get("subscribersLost")),
            pulled_at=now,
        )
        db.execute(stmt.on_conflict_do_update(
            constraint="uq_youtube_daily_analytics_day",
            set_={k: stmt.excluded[k] for k in (
                "views", "estimated_minutes_watched", "average_view_duration_sec",
                "average_view_percentage", "subscribers_gained", "subscribers_lost", "pulled_at")},
        ))
    return len(rows)


def upsert_video_totals(db: Session, period_end: date, window_days: int, rows: list[dict],
                        now: datetime) -> int:
    for r in rows:
        stmt = insert(YoutubeVideoAnalytics).values(
            video_id=r["video"],
            period_end=period_end,
            window_days=window_days,
            views=_int(r.get("views")),
            estimated_minutes_watched=_int(r.get("estimatedMinutesWatched")),
            average_view_duration_sec=_int(r.get("averageViewDuration")),
            average_view_percentage=_float(r.get("averageViewPercentage")),
            pulled_at=now,
        )
        db.execute(stmt.on_conflict_do_update(
            constraint="uq_youtube_video_analytics_period",
            set_={k: stmt.excluded[k] for k in (
                "views", "estimated_minutes_watched", "average_view_duration_sec",
                "average_view_percentage", "pulled_at")},
        ))
    return len(rows)


def pull_youtube_analytics(db: Session, client: Optional[httpx.Client] = None,
                           now: Optional[datetime] = None) -> int:
    settings = get_settings()
    if not settings.youtube_analytics_configured:
        logger.info(
            "YouTube Analytics not connected: YOUTUBE_OAUTH_CLIENT_ID, YOUTUBE_OAUTH_CLIENT_SECRET "
            "and YOUTUBE_OAUTH_REFRESH_TOKEN must all be set (the channel owner approves access "
            "once with scripts/youtube_oauth.py). Nothing pulled.")
        return 0

    now = now or datetime.now(timezone.utc)
    # The last full UTC day. YouTube fills in the most recent days late; the
    # nightly re-pull of the whole window picks them up.
    end = now.date() - timedelta(days=1)
    calls = Calls()
    own_client = client is None
    client = client or httpx.Client()
    try:
        token = refresh_access_token(
            client, settings.youtube_oauth_client_id.strip(),
            settings.youtube_oauth_client_secret.strip(), settings.youtube_oauth_refresh_token.strip())
        channel = fetch_my_channel(client, token, calls)
        # The public-data job may not track this channel yet; record it so the
        # dashboard can name it. Never overwrite what that job wrote.
        db.execute(insert(YoutubeChannel).values(
            channel_id=channel.channel_id, title=channel.title, handle=channel.handle,
            uploads_playlist_id=channel.uploads_playlist_id, thumbnail_url=channel.thumbnail_url,
            updated_at=now,
        ).on_conflict_do_nothing(index_elements=[YoutubeChannel.channel_id]))

        daily = query_report(client, token, {
            "ids": "channel==MINE",
            "startDate": (end - timedelta(days=DAILY_WINDOW_DAYS - 1)).isoformat(),
            "endDate": end.isoformat(),
            "metrics": DAILY_METRICS,
            "dimensions": "day",
            "sort": "day",
        }, calls)
        videos = query_report(client, token, {
            "ids": "channel==MINE",
            "startDate": (end - timedelta(days=VIDEO_WINDOW_DAYS - 1)).isoformat(),
            "endDate": end.isoformat(),
            "metrics": VIDEO_METRICS,
            "dimensions": "video",
            "sort": "-views",
            "maxResults": TOP_VIDEOS,
        }, calls)
    finally:
        if own_client:
            client.close()

    written = upsert_daily(db, channel.channel_id, daily, now)
    written += upsert_video_totals(db, end, VIDEO_WINDOW_DAYS, videos, now)
    db.commit()
    logger.info(
        f"YouTube Analytics {channel.handle or channel.channel_id}: {len(daily)} days, "
        f"{len(videos)} videos through {end} ({calls.count} API calls)")
    upload_to_s3({"channel_id": channel.channel_id, "end": end.isoformat(),
                  "daily": daily, "videos": videos},
                 f"youtube-analytics/{now:%Y-%m-%d}.json")
    return written


def main():
    db = SessionLocal()
    try:
        run_job("run_youtube_analytics", db, pull_youtube_analytics, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
