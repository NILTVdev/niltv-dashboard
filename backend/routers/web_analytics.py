import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.database import get_db, SessionLocal

logger = logging.getLogger(__name__)
from backend.models import (
    GA4DailySnapshot, GSCDailyTotal, GSCQuerySnapshot, GSCPageSnapshot,
)

router = APIRouter(dependencies=[Depends(require_api_key)])


# ── Pydantic response models ────────────────────────────

class GA4Out(BaseModel):
    id: int
    date: datetime
    pulled_at: datetime
    sessions: Optional[int]
    total_users: Optional[int]
    pageviews: Optional[int]
    bounce_rate: Optional[float]
    engagement_rate: Optional[float]
    source: Optional[str]
    medium: Optional[str]

    class Config:
        from_attributes = True


class GSCTotalOut(BaseModel):
    id: int
    date: datetime
    clicks: Optional[int]
    impressions: Optional[int]
    ctr: Optional[float]
    position: Optional[float]

    class Config:
        from_attributes = True


class GSCQueryOut(BaseModel):
    id: int
    date: datetime
    query: str
    clicks: Optional[int]
    impressions: Optional[int]
    ctr: Optional[float]
    position: Optional[float]

    class Config:
        from_attributes = True


class GSCPageOut(BaseModel):
    id: int
    date: datetime
    page: str
    clicks: Optional[int]
    impressions: Optional[int]
    ctr: Optional[float]
    position: Optional[float]

    class Config:
        from_attributes = True


def _cutoff(days: int) -> datetime:
    """Return a UTC datetime N days ago at midnight."""
    return (datetime.now(tz=timezone.utc) - timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


# ── List endpoints ──────────────────────────────────────

@router.get("/ga4", response_model=list[GA4Out])
def list_ga4(days: int = 90, site: str = "truebluetv", db: Session = Depends(get_db)):
    """Return GA4 daily snapshots for the last N days."""
    return (
        db.query(GA4DailySnapshot)
        .filter(GA4DailySnapshot.site == site, GA4DailySnapshot.date >= _cutoff(days))
        .order_by(GA4DailySnapshot.date.desc())
        .all()
    )


@router.get("/gsc", response_model=list[GSCTotalOut])
def list_gsc(days: int = 90, site: str = "truebluetv", db: Session = Depends(get_db)):
    """Return accurate GSC daily totals for the last N days."""
    return (
        db.query(GSCDailyTotal)
        .filter(GSCDailyTotal.site == site, GSCDailyTotal.date >= _cutoff(days))
        .order_by(GSCDailyTotal.date.desc())
        .all()
    )


@router.get("/gsc/queries", response_model=list[GSCQueryOut])
def list_gsc_queries(days: int = 90, site: str = "truebluetv", db: Session = Depends(get_db)):
    """Return GSC per-query snapshots for the last N days."""
    return (
        db.query(GSCQuerySnapshot)
        .filter(GSCQuerySnapshot.site == site, GSCQuerySnapshot.date >= _cutoff(days))
        .order_by(GSCQuerySnapshot.date.desc())
        .all()
    )


@router.get("/gsc/pages", response_model=list[GSCPageOut])
def list_gsc_pages(days: int = 90, site: str = "truebluetv", db: Session = Depends(get_db)):
    """Return GSC per-page snapshots for the last N days."""
    return (
        db.query(GSCPageSnapshot)
        .filter(GSCPageSnapshot.site == site, GSCPageSnapshot.date >= _cutoff(days))
        .order_by(GSCPageSnapshot.date.desc())
        .all()
    )


# ── Summary endpoints ───────────────────────────────────

@router.get("/ga4/summary")
def ga4_summary(days: int = 90, site: str = "truebluetv", db: Session = Depends(get_db)):
    """Aggregate GA4 metrics for the last N days.
    Also returns traffic sources breakdown."""
    cutoff = _cutoff(days)

    totals = db.query(
        func.sum(GA4DailySnapshot.sessions).label("total_sessions"),
        func.sum(GA4DailySnapshot.total_users).label("total_users"),
        func.sum(GA4DailySnapshot.pageviews).label("total_pageviews"),
        func.avg(GA4DailySnapshot.bounce_rate).label("avg_bounce_rate"),
        func.avg(GA4DailySnapshot.engagement_rate).label("avg_engagement_rate"),
    ).filter(GA4DailySnapshot.site == site, GA4DailySnapshot.date >= cutoff).first()

    sources = (
        db.query(
            GA4DailySnapshot.source,
            GA4DailySnapshot.medium,
            func.sum(GA4DailySnapshot.sessions).label("sessions"),
            func.sum(GA4DailySnapshot.total_users).label("users"),
        )
        .filter(GA4DailySnapshot.site == site, GA4DailySnapshot.date >= cutoff)
        .group_by(GA4DailySnapshot.source, GA4DailySnapshot.medium)
        .order_by(desc("sessions"))
        .limit(20)
        .all()
    )

    return {
        "total_sessions": totals.total_sessions or 0 if totals else 0,
        "total_users": totals.total_users or 0 if totals else 0,
        "total_pageviews": totals.total_pageviews or 0 if totals else 0,
        "avg_bounce_rate": float(totals.avg_bounce_rate) if totals and totals.avg_bounce_rate else 0.0,
        "avg_engagement_rate": float(totals.avg_engagement_rate) if totals and totals.avg_engagement_rate else 0.0,
        "traffic_sources": [
            {
                "source": r.source or "(direct)",
                "medium": r.medium or "(none)",
                "sessions": r.sessions or 0,
                "users": r.users or 0,
            }
            for r in sources
        ],
    }


@router.get("/gsc/summary")
def gsc_summary(days: int = 90, site: str = "truebluetv", db: Session = Depends(get_db)):
    """Aggregate GSC metrics from accurate daily totals, plus top queries and pages."""
    cutoff = _cutoff(days)

    # Use daily totals for accurate aggregates (no anonymization)
    totals = db.query(
        func.sum(GSCDailyTotal.clicks).label("total_clicks"),
        func.sum(GSCDailyTotal.impressions).label("total_impressions"),
        func.avg(GSCDailyTotal.ctr).label("avg_ctr"),
        func.avg(GSCDailyTotal.position).label("avg_position"),
    ).filter(GSCDailyTotal.site == site, GSCDailyTotal.date >= cutoff).first()

    # Top queries from the query-specific table
    top_queries = (
        db.query(
            GSCQuerySnapshot.query,
            func.sum(GSCQuerySnapshot.clicks).label("clicks"),
            func.sum(GSCQuerySnapshot.impressions).label("impressions"),
            func.avg(GSCQuerySnapshot.ctr).label("avg_ctr"),
            func.avg(GSCQuerySnapshot.position).label("avg_position"),
        )
        .filter(GSCQuerySnapshot.site == site, GSCQuerySnapshot.date >= cutoff)
        .group_by(GSCQuerySnapshot.query)
        .order_by(desc("clicks"))
        .limit(25)
        .all()
    )

    # Top pages from the page-specific table
    top_pages = (
        db.query(
            GSCPageSnapshot.page,
            func.sum(GSCPageSnapshot.clicks).label("clicks"),
            func.sum(GSCPageSnapshot.impressions).label("impressions"),
            func.avg(GSCPageSnapshot.ctr).label("avg_ctr"),
            func.avg(GSCPageSnapshot.position).label("avg_position"),
        )
        .filter(GSCPageSnapshot.site == site, GSCPageSnapshot.date >= cutoff)
        .group_by(GSCPageSnapshot.page)
        .order_by(desc("clicks"))
        .limit(25)
        .all()
    )

    return {
        "total_clicks": totals.total_clicks or 0 if totals else 0,
        "total_impressions": totals.total_impressions or 0 if totals else 0,
        "avg_ctr": float(totals.avg_ctr) if totals and totals.avg_ctr else 0.0,
        "avg_position": float(totals.avg_position) if totals and totals.avg_position else 0.0,
        "top_queries": [
            {
                "query": r.query,
                "clicks": r.clicks or 0,
                "impressions": r.impressions or 0,
                "avg_ctr": float(r.avg_ctr) if r.avg_ctr else 0.0,
                "avg_position": float(r.avg_position) if r.avg_position else 0.0,
            }
            for r in top_queries
        ],
        "top_pages": [
            {
                "page": r.page,
                "clicks": r.clicks or 0,
                "impressions": r.impressions or 0,
                "avg_ctr": float(r.avg_ctr) if r.avg_ctr else 0.0,
                "avg_position": float(r.avg_position) if r.avg_position else 0.0,
            }
            for r in top_pages
        ],
    }


# ── Manual pull trigger ────────────────────────────────

def _run_pull():
    """Run a 30-day backfill in the background."""
    from backend.jobs.backfill_web_analytics import _backfill
    db = SessionLocal()
    try:
        _backfill(db, days=30)
    except Exception as e:
        logger.error(f"Manual web analytics pull failed: {e}")
    finally:
        db.close()


@router.post("/pull")
def trigger_pull(background_tasks: BackgroundTasks):
    """Trigger a manual web analytics data pull (runs in background)."""
    background_tasks.add_task(_run_pull)
    return {"status": "started", "message": "Web analytics pull started in background"}
