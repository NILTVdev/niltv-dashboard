"""
Cron job: Pull Instagram follower counts and recent posts for all active athletes.

Run:
    python -m backend.jobs.run_instagram

Runs daily at 2:00 AM UTC.
Sequential fetcher: 1 athlete every ~30s (~2/min), no concurrency.
Skips athletes marked ig_accessible=False unless 7 days have passed.
Prints a summary report when done.

Transactions: every fetched athlete is written and committed on its own, so a
row lock on `athletes` lives for milliseconds and cannot form a lock cycle with
a multi-row writer such as precompute_athlete_cache. A deadlock is still
retried once in case a new multi-row writer appears.
"""

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from psycopg2.errors import DeadlockDetected
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import Athlete, AthletePost, AthletePostSnapshot, AthleteSnapshot
from backend.sources.instagram import fetch_ig_profile, IGProfile, REQUEST_INTERVAL
from backend.jobs.ambassadors import run_ambassador_enrichment
from backend.jobs.base import run_job, upload_to_s3
from backend.jobs.precompute import precompute_athlete_cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# Re-check inaccessible accounts after 7 days (they may switch to Creator)
RECHECK_DAYS = 7
# Progress line every N fetched athletes (logging only — every athlete commits).
PROGRESS_EVERY = 25
# One retry after a deadlock, with a short pause so the other writer finishes.
DEADLOCK_RETRY_PAUSE = (0.5, 2.0)


def _should_skip(athlete: Athlete, now: datetime) -> bool:
    """Return True if athlete is marked inaccessible and was checked recently."""
    if athlete.ig_accessible is None or athlete.ig_accessible:
        return False
    if athlete.ig_checked_at is None:
        return False  # never checked — try it
    return (now - athlete.ig_checked_at) < timedelta(days=RECHECK_DAYS)


@dataclass
class _AthleteOutcome:
    posts_inserted: int = 0
    new_inaccessible: int = 0
    rechecked_accessible: int = 0
    new_post_ids: set[str] = field(default_factory=set)


def _write_athlete(db: Session, athlete: Athlete, profile: IGProfile, pulled_at: datetime,
                   existing_post_ids: set[str]) -> _AthleteOutcome:
    """Stage one athlete's rows (accessibility flags, profile snapshot, posts and
    their engagement snapshots) on the session. Nothing is committed here, and
    nothing outside the session is mutated, so a rolled-back attempt can be
    replayed by calling this again."""
    out = _AthleteOutcome()

    was_accessible = athlete.ig_accessible
    athlete.ig_checked_at = pulled_at
    if not profile.is_accessible:
        if was_accessible is not False:
            out.new_inaccessible += 1
        athlete.ig_accessible = False
    elif not profile.error:
        if was_accessible is False:
            out.rechecked_accessible += 1
        athlete.ig_accessible = True

    # Update ig_user_id if newly discovered
    if profile.ig_user_id and not athlete.ig_user_id:
        athlete.ig_user_id = profile.ig_user_id

    # Write snapshot (even for errors — keeps the timeline consistent)
    db.add(AthleteSnapshot(
        athlete_id=athlete.id,
        pulled_at=pulled_at,
        ig_followers=profile.followers,
        ig_posts=profile.post_count,
        ig_bio=profile.bio,
    ))

    # Upsert posts + record engagement snapshots
    for p in profile.posts:
        if p.ig_post_id in existing_post_ids or p.ig_post_id in out.new_post_ids:
            existing = (
                db.query(AthletePost)
                .filter(AthletePost.ig_post_id == p.ig_post_id)
                .first()
            )
            if existing:
                if p.like_count is not None:
                    existing.like_count = p.like_count
                if p.comment_count is not None:
                    existing.comment_count = p.comment_count
                # Record engagement snapshot
                db.add(AthletePostSnapshot(
                    post_id=existing.id,
                    captured_at=pulled_at,
                    like_count=p.like_count,
                    comment_count=p.comment_count,
                ))
        else:
            new_post = AthletePost(
                athlete_id=athlete.id,
                ig_post_id=p.ig_post_id,
                posted_at=p.posted_at,
                media_type=p.media_type,
                like_count=p.like_count,
                comment_count=p.comment_count,
                permalink=p.permalink,
                caption=p.caption,
                media_url=p.media_url,
            )
            db.add(new_post)
            db.flush()  # assigns new_post.id
            # Record initial engagement snapshot
            db.add(AthletePostSnapshot(
                post_id=new_post.id,
                captured_at=pulled_at,
                like_count=p.like_count,
                comment_count=p.comment_count,
            ))
            out.new_post_ids.add(p.ig_post_id)
            out.posts_inserted += 1
    return out


def _is_deadlock(exc: BaseException) -> bool:
    return isinstance(exc, OperationalError) and isinstance(exc.orig, DeadlockDetected)


def _commit_athlete(db: Session, athlete: Athlete, profile: IGProfile, pulled_at: datetime,
                    existing_post_ids: set[str], label: str = "") -> _AthleteOutcome:
    """Write + commit one athlete. On a deadlock the attempt is rolled back
    (which expires the athlete row, so the next attempt re-reads it) and
    replayed once from the in-memory profile; a second deadlock propagates so
    run_job alerts. `existing_post_ids` is only extended after a successful
    commit, so a rolled-back insert is never mistaken for an existing post."""
    for attempt in (1, 2):
        try:
            out = _write_athlete(db, athlete, profile, pulled_at, existing_post_ids)
            db.commit()
            existing_post_ids |= out.new_post_ids
            return out
        except OperationalError as e:
            db.rollback()
            if attempt == 2 or not _is_deadlock(e):
                raise
            logger.warning(f"  {label} deadlock on commit — retrying once")
            time.sleep(random.uniform(*DEADLOCK_RETRY_PAUSE))
    raise AssertionError("unreachable")


def _pull_instagram(db: Session) -> int:
    athletes = (
        db.query(Athlete)
        .filter(Athlete.active == True, Athlete.ig_handle.isnot(None))
        .order_by(Athlete.name)
        .all()
    )

    total = len(athletes)
    logger.info(f"Pulling Instagram for {total} athletes...")

    if not athletes:
        return 0

    pulled_at = datetime.now(tz=timezone.utc)

    # Pre-fetch all existing post IDs in one query
    athlete_ids = [a.id for a in athletes]
    all_existing_post_ids: set[str] = set()
    if athlete_ids:
        rows = (
            db.query(AthletePost.ig_post_id)
            .filter(AthletePost.athlete_id.in_(athlete_ids))
            .all()
        )
        all_existing_post_ids = {r[0] for r in rows if r[0]}

    # Report counters
    success_count = 0
    error_count = 0
    skipped_count = 0
    new_inaccessible = 0
    rechecked_accessible = 0
    posts_inserted = 0
    backup_data = []

    fetched = 0
    for i, athlete in enumerate(athletes, 1):
        # Skip inaccessible accounts unless 7 days have passed
        if _should_skip(athlete, pulled_at):
            skipped_count += 1
            logger.info(f"  [{i}/{total}] SKIP @{athlete.ig_handle} (inaccessible, checked {athlete.ig_checked_at:%Y-%m-%d})")
            continue

        # Sleep between requests (~30s = 2 athletes/min)
        if i > 1:
            time.sleep(random.uniform(*REQUEST_INTERVAL))

        logger.info(f"  [{i}/{total}] Fetching @{athlete.ig_handle}...")
        profile = fetch_ig_profile(athlete.ig_handle)

        if not profile.is_accessible:
            logger.warning(f"  [{i}/{total}] INACCESSIBLE @{athlete.ig_handle}: {profile.error[:60] if profile.error else 'unknown'}")
            error_count += 1
        elif profile.error:
            logger.warning(f"  [{i}/{total}] ERROR @{athlete.ig_handle}: {profile.error[:60]}")
            error_count += 1
        else:
            logger.info(f"  [{i}/{total}] OK @{athlete.ig_handle}: {profile.followers} followers, {len(profile.posts)} posts")
            success_count += 1

        # One short transaction per athlete (see module docstring).
        outcome = _commit_athlete(db, athlete, profile, pulled_at, all_existing_post_ids,
                                  label=f"[{i}/{total}] @{athlete.ig_handle}")
        posts_inserted += outcome.posts_inserted
        new_inaccessible += outcome.new_inaccessible
        rechecked_accessible += outcome.rechecked_accessible

        backup_data.append({
            "athlete_id": athlete.id,
            "name": athlete.name,
            "ig_handle": athlete.ig_handle,
            "ig_user_id": profile.ig_user_id,
            "followers": profile.followers,
            "post_count": profile.post_count,
            "bio": profile.bio,
            "error": profile.error,
            "is_accessible": profile.is_accessible,
            "posts": [
                {
                    "ig_post_id": p.ig_post_id,
                    "posted_at": p.posted_at.isoformat() if p.posted_at else None,
                    "media_type": p.media_type,
                    "like_count": p.like_count,
                    "comment_count": p.comment_count,
                    "permalink": p.permalink,
                }
                for p in profile.posts
            ],
        })

        fetched += 1
        if fetched % PROGRESS_EVERY == 0:
            logger.info(f"  --- progress: {fetched} fetched, {i}/{total} walked ---")

    # ── Summary Report ──────────────────────────────────────────
    finished_at = datetime.now(tz=timezone.utc)
    elapsed = finished_at - pulled_at
    elapsed_min = elapsed.total_seconds() / 60

    report = (
        f"\n{'='*60}\n"
        f"  INSTAGRAM PULL REPORT\n"
        f"  {pulled_at:%Y-%m-%d %H:%M UTC} → {finished_at:%H:%M UTC} ({elapsed_min:.0f} min)\n"
        f"{'='*60}\n"
        f"  Total athletes:       {total}\n"
        f"  Fetched successfully: {success_count}\n"
        f"  Errors:               {error_count}\n"
        f"  Skipped (cached):     {skipped_count}\n"
        f"  New posts inserted:   {posts_inserted}\n"
        f"  Newly inaccessible:   {new_inaccessible}\n"
        f"  Re-checked → OK:      {rechecked_accessible}\n"
        f"{'='*60}\n"
    )
    logger.info(report)

    # JSON backup to S3
    date_str = pulled_at.strftime("%Y-%m-%d")
    upload_to_s3(backup_data, f"backups/instagram/{date_str}.json")

    return posts_inserted


def main():
    db = SessionLocal()
    try:
        run_job("run_instagram", db, _pull_instagram, db)
        logger.info("Running athlete cache precompute...")
        precompute_athlete_cache(db)
        # Profile-only Business Discovery for confirmed ambassadors (never
        # their post history). Never raises — see backend/jobs/ambassadors.py.
        logger.info("Running ambassador enrichment...")
        run_ambassador_enrichment(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
