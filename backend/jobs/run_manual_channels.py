"""
Cron job: nightly Business Discovery pull for MANUAL channels.

A manual channel is a brand_accounts row with api='bd': an owned channel no
token can act for (today: truebluetv; no token is available for this
account). Business Discovery reads any professional
account's PUBLIC profile and owned media through our own @niltv token with no
permission on the target, so this job gives such a channel what run_brand_ig
gives the others, minus owner-only insights:

    brand_snapshots ....... followers, post count, bio (drives health + follower deltas)
    niltv_network_posts ... the account's own posts (Graph ids, likes, comments,
                            permalink, caption, media type) tagged collab_accounts=<account>

What Business Discovery cannot see: views, shares, saves, reach, follows, and
posts the account did not author (athlete collabs on its grid). Those arrive via
CSV upload (a grid snapshot or the Business Suite export). All three sources
merge per permalink in import_niltv_network.upsert_posts.

Schedule: daily at 5:45 AM UTC.
Manual:  python -m backend.jobs.run_manual_channels
"""

import logging
import random
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.jobs.base import run_job
from backend.jobs.import_niltv_network import SOURCE_BD, upsert_posts
from backend.models import BrandAccount, BrandSnapshot
from backend.sources.instagram import REQUEST_INTERVAL, fetch_ig_profile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# Business Discovery media_type -> the canonical post_type vocabulary
# (import_niltv_network.normalize_post_type). Owned videos on these channels are
# reels in practice; a plain feed video is indistinguishable here.
POST_TYPE = {"IMAGE": "IMAGE", "CAROUSEL_ALBUM": "CAROUSEL_ALBUM", "VIDEO": "REELS"}


def manual_channels(db: Session) -> list[BrandAccount]:
    return (
        db.query(BrandAccount)
        .filter(BrandAccount.api == "bd", BrandAccount.username.isnot(None), BrandAccount.username != "")
        .order_by(BrandAccount.account)
        .all()
    )


def _rows_from_profile(account: str, profile) -> list[dict]:
    rows = []
    for p in profile.posts:
        if not p.ig_post_id:
            continue
        rows.append({
            "post_id": p.ig_post_id,
            "account_username": profile.username,
            "account_name": profile.name,
            "description": p.caption,
            "duration_sec": None,
            "publish_time": p.posted_at,
            "permalink": p.permalink,
            "post_type": POST_TYPE.get(p.media_type or "", p.media_type),
            "media_url": p.media_url,
            "thumbnail_url": None,
            "collab_accounts": account,
            "views": None,
            "likes": p.like_count,
            "shares": None,
            "comments": p.comment_count,
            "saves": None,
            "reach": None,
            "follows": None,
        })
    return rows


def _pull_manual_channels(db: Session) -> int:
    channels = manual_channels(db)
    if not channels:
        logger.info("No manual channels (brand_accounts.api='bd') — nothing to do.")
        return 0

    pulled_at = datetime.now(tz=timezone.utc)
    inserted_total = 0
    for i, row in enumerate(channels):
        if i:
            time.sleep(random.uniform(*REQUEST_INTERVAL))
        logger.info(f"[{row.account}] Business Discovery for @{row.username}...")
        profile = fetch_ig_profile(row.username, include_media=True)

        if profile.error or not profile.is_accessible:
            # Same sentinel convention as run_brand_ig: empty username = failed attempt,
            # so the registry shows health=failing instead of silently going stale.
            logger.error(f"[{row.account}] Business Discovery failed: {profile.error or 'not accessible'}")
            db.add(BrandSnapshot(account=row.account, pulled_at=pulled_at, username="",
                                 followers=None, post_count=None, bio=None))
            db.commit()
            continue

        db.add(BrandSnapshot(
            account=row.account, pulled_at=pulled_at, username=profile.username,
            followers=profile.followers, post_count=profile.post_count, bio=profile.bio,
        ))
        db.commit()

        rows = _rows_from_profile(row.account, profile)
        inserted, updated = upsert_posts(db, rows, captured_at=pulled_at, source=SOURCE_BD)
        inserted_total += inserted
        logger.info(
            f"[{row.account}] @{profile.username}: {profile.followers} followers, "
            f"{profile.post_count} posts; {len(rows)} owned posts seen, "
            f"{inserted} new, {updated} updated."
        )
    return inserted_total


def main():
    db = SessionLocal()
    try:
        run_job("run_manual_channels", db, _pull_manual_channels, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
