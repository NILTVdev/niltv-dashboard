from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.database import get_db
from sqlalchemy import cast, Date
from backend.models import AthletePost, AthletePostSnapshot, ZoomphPost

router = APIRouter(dependencies=[Depends(require_api_key)])


class PostOut(BaseModel):
    id: int
    athlete_id: int
    ig_post_id: str
    posted_at: Optional[datetime]
    media_type: Optional[str]
    like_count: Optional[int]
    comment_count: Optional[int]
    engagement: Optional[int] = None
    permalink: Optional[str]
    caption: Optional[str]
    media_url: Optional[str]
    # Zoomph cross-populated fields (only for IG posts matched in Zoomph)
    impressions: Optional[int] = None
    reach: Optional[int] = None
    post_value: Optional[float] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_post(
        cls,
        post: "AthletePost",
        zoomph: Optional["ZoomphPost"] = None,
    ) -> "PostOut":
        likes = post.like_count or 0
        comments = post.comment_count or 0
        engagement = (likes + comments) if (post.like_count is not None or post.comment_count is not None) else None
        return cls(
            id=post.id,
            athlete_id=post.athlete_id,
            ig_post_id=post.ig_post_id,
            posted_at=post.posted_at,
            media_type=post.media_type,
            like_count=post.like_count,
            comment_count=post.comment_count,
            engagement=engagement,
            permalink=post.permalink,
            caption=post.caption,
            media_url=post.media_url,
            impressions=zoomph.impressions if zoomph else None,
            reach=zoomph.reach if zoomph else None,
            post_value=float(zoomph.post_value) if zoomph and zoomph.post_value is not None else None,
        )


@router.get("/athletes/{athlete_id}", response_model=list[PostOut])
def get_athlete_posts(
    athlete_id: int,
    limit: int = 25,
    db: Session = Depends(get_db),
):
    posts = (
        db.query(AthletePost)
        .filter(AthletePost.athlete_id == athlete_id)
        .order_by(AthletePost.posted_at.desc())
        .limit(limit)
        .all()
    )

    # Cross-populate: match athlete IG posts against Zoomph by permalink/url
    permalinks = [p.permalink for p in posts if p.permalink]
    zoomph_map: dict[str, ZoomphPost] = {}
    if permalinks:
        zoomph_matches = (
            db.query(ZoomphPost)
            .filter(ZoomphPost.url.in_(permalinks))
            .all()
        )
        zoomph_map = {z.url: z for z in zoomph_matches}

    return [
        PostOut.from_post(p, zoomph_map.get(p.permalink))
        for p in posts
    ]


@router.get("/athletes/{athlete_id}/engagement-by-day")
def get_engagement_by_day(
    athlete_id: int,
    db: Session = Depends(get_db),
):
    """Likes and comments an athlete's posts gained on each snapshot date.

    Each value is the change that day, summed per post, so adding the days up
    gives the athlete's current total. The first date holds the starting total.
    A post's first snapshot counts in full on that date. Snapshots stop once a
    post leaves the latest pull, so comparing daily sums directly would read a
    post leaving as lost likes; comparing each post with its own last value
    avoids that.
    """
    post_ids_q = (
        db.query(AthletePost.id)
        .filter(AthletePost.athlete_id == athlete_id)
        .subquery()
    )
    rows = (
        db.query(
            AthletePostSnapshot.post_id,
            cast(AthletePostSnapshot.captured_at, Date).label("date"),
            AthletePostSnapshot.like_count,
            AthletePostSnapshot.comment_count,
        )
        .filter(AthletePostSnapshot.post_id.in_(post_ids_q.select()))
        .order_by(AthletePostSnapshot.post_id, AthletePostSnapshot.captured_at)
        .all()
    )

    days: dict = {}
    last: dict = {}
    for r in rows:
        day = days.setdefault(r.date, {"likes": 0, "comments": 0})
        for field, value in (("likes", r.like_count), ("comments", r.comment_count)):
            previous = last.get((r.post_id, field))
            # A hidden count arrives as NULL, or as 0 on older rows. Neither is
            # a real drop, so keep the last known value for the next comparison.
            if value is None or (value == 0 and previous):
                continue
            day[field] += value - (previous or 0)
            last[(r.post_id, field)] = value

    return [
        {"date": date.isoformat(), "likes": totals["likes"], "comments": totals["comments"]}
        for date, totals in sorted(days.items())
    ]
