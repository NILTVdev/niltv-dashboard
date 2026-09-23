"""
Precompute cached values on the athletes table.

Called after each cron job (run_instagram, run_zoomph) so that
API endpoints can read cached columns instead of recomputing on every request.
"""

import logging

from sqlalchemy import func as sqlfunc, text
from sqlalchemy.orm import Session

from backend.models import (
    Ambassador,
    AmbassadorSnapshot,
    Athlete,
    AthletePost,
    AthleteSnapshot,
    NiltvNetworkPost,
    ZoomphPost,
)

logger = logging.getLogger(__name__)


def precompute_athlete_cache(db: Session) -> None:
    """Refresh all cached_* columns on the athletes table.

    One transaction over every active athlete, walked in primary-key order so
    any other multi-row athlete writer that also orders by id cannot deadlock
    with it (run_instagram commits per athlete and never holds two rows)."""
    athletes = db.query(Athlete).filter(Athlete.active == True).order_by(Athlete.id).all()
    if not athletes:
        return

    athlete_ids = [a.id for a in athletes]
    athlete_map = {a.id: a for a in athletes}

    # 1. Batch latest snapshots via DISTINCT ON
    snap_subq = (
        db.query(
            AthleteSnapshot.athlete_id,
            AthleteSnapshot.ig_followers,
            AthleteSnapshot.ig_posts,
            AthleteSnapshot.ig_bio,
            AthleteSnapshot.pulled_at,
        )
        .filter(AthleteSnapshot.athlete_id.in_(athlete_ids))
        .distinct(AthleteSnapshot.athlete_id)
        .order_by(AthleteSnapshot.athlete_id, AthleteSnapshot.pulled_at.desc())
        .all()
    )
    snap_map = {r.athlete_id: r for r in snap_subq}

    # 2. Batch IG engagement (likes + comments per athlete)
    ig_rows = (
        db.query(
            AthletePost.athlete_id,
            sqlfunc.coalesce(sqlfunc.sum(AthletePost.like_count), 0).label("total_likes"),
            sqlfunc.coalesce(sqlfunc.sum(AthletePost.comment_count), 0).label("total_comments"),
        )
        .filter(AthletePost.athlete_id.in_(athlete_ids))
        .group_by(AthletePost.athlete_id)
        .all()
    )
    ig_eng_map: dict[int, int] = {}
    for r in ig_rows:
        total = int(r.total_likes) + int(r.total_comments)
        if total > 0:
            ig_eng_map[r.athlete_id] = total

    # 3. Attributed engagement from Zoomph mentions
    handle_athletes = (
        db.query(Athlete.id, Athlete.ig_handle)
        .filter(Athlete.id.in_(athlete_ids), Athlete.ig_handle.isnot(None))
        .all()
    )
    handle_to_ids: dict[str, list[int]] = {}
    for a_id, handle in handle_athletes:
        key = handle.lstrip("@").strip().lower()
        if key:
            handle_to_ids.setdefault(key, []).append(a_id)

    attr_eng_map: dict[int, int] = {}
    if handle_to_ids:
        zoomph_posts = (
            db.query(
                ZoomphPost.mentions,
                ZoomphPost.engagement,
                ZoomphPost.like_count,
                ZoomphPost.comment_count,
                ZoomphPost.save_count,
                ZoomphPost.share_count,
                ZoomphPost.reply_count,
                ZoomphPost.impressions,
            )
            .filter(ZoomphPost.mentions.isnot(None), ZoomphPost.mentions != "")
            .all()
        )
        for zp in zoomph_posts:
            mention_handles = [
                m.lstrip("@").strip().lower()
                for m in (zp.mentions or "").replace(",", " ").split()
                if m.strip()
            ]
            post_eng = (
                (zp.engagement or 0)
                + (zp.like_count or 0)
                + (zp.comment_count or 0)
                + (zp.save_count or 0)
                + (zp.share_count or 0)
                + (zp.reply_count or 0)
                + (zp.impressions or 0)
            )
            if post_eng == 0:
                continue
            for mention in mention_handles:
                for a_id in handle_to_ids.get(mention, []):
                    attr_eng_map[a_id] = attr_eng_map.get(a_id, 0) + post_eng

    # 4. Write cached values
    updated = 0
    for a_id, athlete in athlete_map.items():
        snap = snap_map.get(a_id)
        ig_eng = ig_eng_map.get(a_id)
        attr_eng = attr_eng_map.get(a_id)
        parts = [v for v in (ig_eng, attr_eng) if v]
        valuation = sum(parts) if parts else None

        athlete.cached_ig_followers = snap.ig_followers if snap else None
        athlete.cached_ig_posts = snap.ig_posts if snap else None
        athlete.cached_ig_bio = snap.ig_bio if snap else None
        athlete.cached_ig_engagement = ig_eng
        athlete.cached_attributed_eng = attr_eng
        athlete.cached_social_valuation = valuation
        athlete.cached_last_pulled = snap.pulled_at if snap else None
        updated += 1

    db.commit()
    logger.info(f"Precomputed cache for {updated} athletes")


def precompute_ambassador_cache(db: Session) -> None:
    """Refresh cached_* columns on the ambassadors table.

    Collab rollups come from niltv_network_posts, the one network table since
    migration 026 (one row per IG post, so nothing double-counts). Profile numbers come from ambassador_snapshots,
    or from the athlete pipeline's snapshots when the row is athlete-linked.
    """
    ambassadors = db.query(Ambassador).filter(Ambassador.status != "removed").all()
    if not ambassadors:
        return

    ids = [a.id for a in ambassadors]

    # 1. Collab rollups per ambassador
    rollup_rows = (
        db.query(
            NiltvNetworkPost.ambassador_id,
            sqlfunc.count(NiltvNetworkPost.id).label("posts"),
            sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.views), 0).label("views"),
            sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.likes), 0).label("likes"),
            sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.comments), 0).label("comments"),
            sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.shares), 0).label("shares"),
            sqlfunc.coalesce(sqlfunc.sum(NiltvNetworkPost.saves), 0).label("saves"),
        )
        .filter(NiltvNetworkPost.ambassador_id.in_(ids))
        .group_by(NiltvNetworkPost.ambassador_id)
        .all()
    )
    rollup_map = {r.ambassador_id: r for r in rollup_rows}

    # 2. Latest own profile snapshot per ambassador
    snap_rows = (
        db.query(AmbassadorSnapshot)
        .filter(AmbassadorSnapshot.ambassador_id.in_(ids))
        .distinct(AmbassadorSnapshot.ambassador_id)
        .order_by(AmbassadorSnapshot.ambassador_id, AmbassadorSnapshot.pulled_at.desc())
        .all()
    )
    snap_map = {s.ambassador_id: s for s in snap_rows}

    # 3. Athlete-linked rows read the athlete pipeline's cache instead
    athlete_ids = [a.athlete_id for a in ambassadors if a.athlete_id]
    athlete_map = {}
    if athlete_ids:
        athlete_map = {
            a.id: a for a in db.query(Athlete).filter(Athlete.id.in_(athlete_ids)).all()
        }

    for ambassador in ambassadors:
        rollup = rollup_map.get(ambassador.id)
        ambassador.cached_collab_posts = int(rollup.posts) if rollup else 0
        ambassador.cached_collab_views = int(rollup.views) if rollup else None
        ambassador.cached_collab_engagement = (
            int(rollup.likes) + int(rollup.comments) + int(rollup.shares) + int(rollup.saves)
            if rollup else None
        )

        athlete = athlete_map.get(ambassador.athlete_id) if ambassador.athlete_id else None
        if athlete is not None:
            ambassador.cached_followers = athlete.cached_ig_followers
            ambassador.cached_bio = athlete.cached_ig_bio
            ambassador.cached_last_pulled = athlete.cached_last_pulled
        else:
            snap = snap_map.get(ambassador.id)
            ambassador.cached_followers = snap.followers if snap else None
            ambassador.cached_bio = snap.bio if snap else None
            ambassador.cached_last_pulled = snap.pulled_at if snap else None

    db.commit()
    logger.info(f"Precomputed cache for {len(ambassadors)} ambassadors")
