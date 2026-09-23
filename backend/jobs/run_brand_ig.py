"""
Cron job: Pull Instagram profile and posts for the owned brand accounts.

Run:
    scripts/run_job.sh backend.jobs.run_brand_ig

Runs hourly at :10 (after the jobs that start on the hour).
For each account in the merged registry (brand_accounts table + legacy .env
entries — see backend/brand_registry.py) fetches profile + recent posts +
per-post insights (views, reach, saves, shares). Rows are tagged with the
`account` discriminator. Onboard new campus channels with
scripts/add_brand_account.py — they are picked up on the next run.

Owned-account insights are also copied onto matching niltv_network_posts rows
(matched by permalink shortcode) — the collab fetch can't read shares/saves/
reach for posts @niltv doesn't own, but the owner's own token can.
"""

import logging
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.brand_registry import get_brand_targets
from backend.database import SessionLocal
from backend.jobs.ambassadors import run_welcome_scan
from backend.jobs.base import run_job, upload_to_s3
from backend.models import BrandPost, BrandSnapshot, NiltvNetworkPost
from backend.sources.brand_ig import fetch_brand_profile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

_SHORTCODE_RE = re.compile(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)")


def upsert_brand_posts(db: Session, account: str, posts: list, pulled_at: datetime) -> int:
    """Insert new brand posts / refresh metrics on existing ones (None never
    overwrites a stored value). Returns the number of inserted rows."""
    existing_ids: set[str] = {r[0] for r in db.query(BrandPost.ig_post_id).all() if r[0]}

    inserted = 0
    for p in posts:
        if p.ig_post_id in existing_ids:
            existing = db.query(BrandPost).filter(BrandPost.ig_post_id == p.ig_post_id).first()
            if existing:
                if p.like_count is not None:
                    existing.like_count = p.like_count
                if p.comment_count is not None:
                    existing.comment_count = p.comment_count
                if p.impressions is not None:
                    existing.impressions = p.impressions
                if p.reach is not None:
                    existing.reach = p.reach
                if p.saves is not None:
                    existing.saves = p.saves
                if p.views is not None:
                    existing.views = p.views
                if p.shares is not None:
                    existing.shares = p.shares
                # IG CDN media URLs expire within hours — refresh on every pull
                # so the app's ingest bridge (which mirrors the media right
                # after this job) always has a live URL. Caption edits ride along.
                if p.media_url:
                    existing.media_url = p.media_url
                if p.thumbnail_url:
                    existing.thumbnail_url = p.thumbnail_url
                if p.caption is not None:
                    existing.caption = p.caption
                existing.updated_at = pulled_at
        else:
            db.add(BrandPost(
                account=account,
                ig_post_id=p.ig_post_id,
                posted_at=p.posted_at,
                media_type=p.media_type,
                like_count=p.like_count,
                comment_count=p.comment_count,
                permalink=p.permalink,
                caption=p.caption,
                media_url=p.media_url,
                thumbnail_url=p.thumbnail_url,
                impressions=p.impressions,
                reach=p.reach,
                saves=p.saves,
                views=p.views,
                shares=p.shares,
                pulled_at=pulled_at,
            ))
            existing_ids.add(p.ig_post_id)
            inserted += 1

    db.commit()
    return inserted


def enrich_network_from_brand(db: Session, posts: list, pulled_at: datetime) -> int:
    """Copy owned-account insights onto matching niltv_network_posts rows.

    Network rows for posts @niltv doesn't own carry NULL shares/saves/reach
    (IG only exposes insights to the owner). When the owner is one of OUR
    brand accounts, its direct pull has the real numbers — match by permalink
    shortcode and overwrite. Update-only: never inserts network rows, so the
    collab table keeps its own membership. Returns rows updated."""
    updated = 0
    for p in posts:
        if not p.permalink:
            continue
        m = _SHORTCODE_RE.search(p.permalink)
        if not m:
            continue
        # Escape LIKE wildcards — shortcodes may contain "_" (any-char in LIKE).
        code = m.group(1).replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        rows = (
            db.query(NiltvNetworkPost)
            .filter(NiltvNetworkPost.permalink.like(f"%/{code}/%", escape="\\"))
            .all()
        )
        for row in rows:
            changed = False
            for net_field, val in (
                ("views", p.views),
                ("reach", p.reach),
                ("likes", p.like_count),
                ("comments", p.comment_count),
                ("shares", p.shares),
                ("saves", p.saves),
            ):
                if val is not None and getattr(row, net_field) != val:
                    setattr(row, net_field, val)
                    changed = True
            if p.reach is not None and row.projected_reach is not None:
                row.projected_reach = None
                changed = True
            if changed:
                row.updated_at = pulled_at
                updated += 1
    db.commit()
    return updated


def _pull_account(
    db: Session, account: str, ig_user_id: str, access_token: str, limit: int,
    pulled_at: datetime, api: str = "fb"
) -> int:
    logger.info(f"Fetching brand Instagram profile and posts for account={account} (api={api})...")

    profile = fetch_brand_profile(
        ig_user_id=ig_user_id, access_token=access_token, limit=limit, api=api
    )

    if profile.error:
        logger.error(f"[{account}] Profile fetch failed: {profile.error}")
        db.add(BrandSnapshot(account=account, pulled_at=pulled_at, username="", followers=None, post_count=None, bio=None))
        db.commit()
        return 0

    logger.info(
        f"@{profile.username}: {profile.followers} followers, "
        f"{profile.post_count} posts, {len(profile.posts)} fetched"
    )

    db.add(BrandSnapshot(
        account=account,
        pulled_at=pulled_at,
        username=profile.username,
        followers=profile.followers,
        post_count=profile.post_count,
        bio=profile.bio,
    ))

    inserted = upsert_brand_posts(db, account, profile.posts, pulled_at)
    enriched = enrich_network_from_brand(db, profile.posts, pulled_at)

    backup_data = {
        "account": account,
        "username": profile.username,
        "followers": profile.followers,
        "post_count": profile.post_count,
        "bio": profile.bio,
        "posts": [
            {
                "ig_post_id": p.ig_post_id,
                "posted_at": p.posted_at.isoformat() if p.posted_at else None,
                "media_type": p.media_type,
                "like_count": p.like_count,
                "comment_count": p.comment_count,
                "permalink": p.permalink,
                "impressions": p.impressions,
                "reach": p.reach,
                "saves": p.saves,
                "views": p.views,
                "shares": p.shares,
            }
            for p in profile.posts
        ],
    }
    date_str = pulled_at.strftime("%Y-%m-%d")
    # @niltv keeps its legacy backup path; additional accounts get a suffix.
    key = f"backups/brand_ig/{date_str}.json" if account == "niltv" else f"backups/brand_ig_{account}/{date_str}.json"
    upload_to_s3(backup_data, key)

    logger.info(
        f"[{account}] pull complete: {inserted} new posts, "
        f"{len(profile.posts) - inserted} updated, {enriched} network rows enriched."
    )
    return inserted


def _pull_brand_ig(db: Session) -> int:
    targets = get_brand_targets(db)
    if not targets:
        logger.error("No brand accounts configured (brand_accounts table or BRAND_IG_* env) — aborting.")
        return 0

    pulled_at = datetime.now(tz=timezone.utc)

    total_inserted = 0
    for target in targets:
        total_inserted += _pull_account(
            db,
            account=target["account"],
            ig_user_id=target["ig_user_id"],
            access_token=target["access_token"],
            limit=target["limit"],
            pulled_at=pulled_at,
            api=target.get("api", "fb"),
        )

    # Ambassador discovery from "welcome our new ambassador @x" captions.
    # Never raises — a parser problem must not fail the media pull.
    run_welcome_scan(db)

    return total_inserted


def main():
    db = SessionLocal()
    try:
        run_job("run_brand_ig", db, _pull_brand_ig, db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
