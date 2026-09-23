from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.database import get_db
from backend.models import AthleteSnapshot

router = APIRouter(dependencies=[Depends(require_api_key)])


class SnapshotOut(BaseModel):
    id: int
    athlete_id: int
    pulled_at: datetime
    ig_followers: Optional[int]
    ig_posts: Optional[int]
    ig_bio: Optional[str]
    tiktok_followers: Optional[int]
    tiktok_likes: Optional[int]
    x_followers: Optional[int]
    x_posts: Optional[int]

    class Config:
        from_attributes = True


@router.get("/athletes/{athlete_id}", response_model=list[SnapshotOut])
def get_athlete_snapshots(
    athlete_id: int,
    limit: int = 90,
    db: Session = Depends(get_db),
):
    """Returns up to `limit` snapshots for an athlete, newest first.
    Default of 90 covers ~3 months of every-2-day pulls."""
    return (
        db.query(AthleteSnapshot)
        .filter(AthleteSnapshot.athlete_id == athlete_id)
        .order_by(AthleteSnapshot.pulled_at.desc())
        .limit(limit)
        .all()
    )
