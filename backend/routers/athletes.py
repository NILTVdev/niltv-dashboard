from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.database import get_db
from backend.models import Athlete

router = APIRouter(dependencies=[Depends(require_api_key)])


class AthleteOut(BaseModel):
    id: int
    name: str
    sport: Optional[str]
    year: Optional[str]
    ig_handle: Optional[str]
    tiktok_handle: Optional[str]
    x_handle: Optional[str]
    active: bool
    # Cached values (precomputed after each cron job)
    ig_followers: Optional[int] = None
    ig_posts: Optional[int] = None
    tiktok_followers: Optional[int] = None
    x_followers: Optional[int] = None
    last_pulled: Optional[datetime] = None
    social_valuation: Optional[int] = None
    ig_engagement: Optional[int] = None
    attributed_engagement: Optional[int] = None

    class Config:
        from_attributes = True


def _to_out(athlete: Athlete) -> AthleteOut:
    return AthleteOut(
        id=athlete.id,
        name=athlete.name,
        sport=athlete.sport,
        year=athlete.year,
        ig_handle=athlete.ig_handle,
        tiktok_handle=athlete.tiktok_handle,
        x_handle=athlete.x_handle,
        active=athlete.active,
        ig_followers=athlete.cached_ig_followers,
        ig_posts=athlete.cached_ig_posts,
        tiktok_followers=None,
        x_followers=None,
        last_pulled=athlete.cached_last_pulled,
        social_valuation=athlete.cached_social_valuation,
        ig_engagement=athlete.cached_ig_engagement,
        attributed_engagement=athlete.cached_attributed_eng,
    )


@router.get("/", response_model=list[AthleteOut])
def list_athletes(active_only: bool = True, db: Session = Depends(get_db)):
    query = db.query(Athlete)
    if active_only:
        query = query.filter(Athlete.active == True)
    athletes = query.order_by(Athlete.name).all()
    return [_to_out(a) for a in athletes]


@router.get("/{athlete_id}", response_model=AthleteOut)
def get_athlete(athlete_id: int, db: Session = Depends(get_db)):
    athlete = db.query(Athlete).filter(Athlete.id == athlete_id).first()
    if not athlete:
        raise HTTPException(status_code=404, detail="Athlete not found")
    return _to_out(athlete)
