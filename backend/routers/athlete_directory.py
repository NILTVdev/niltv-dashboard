"""Athlete directory: one searchable list over the roster, the ambassador
registry and the signups (merge rules in backend/athlete_directory.py).

Read access: admin and general (backend/accounts.py lists the prefix with the
roster pages); demo is refused there. Contact fields and free-text application
answers are added to the detail response for admins (and service callers)
only, and the CSV export is admin-only, so a general account never receives
them, whatever the page shows.

Defaults enforced here, not in the page:
  * Declined signups are left out of the list, the facets and the detail
    route. ``include_declined=true`` brings them back, for admins only (403
    for anyone else).
  * directory.ADMIN_ONLY_FIELDS (NIL deals done and wanted, content
    description) are null in every response to a non-admin.
"""

import csv
import io
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend import athlete_directory as directory
from backend.auth import require_api_key
from backend.database import get_db
from backend.models import AmbassadorSnapshot, AthleteSnapshot, NiltvNetworkPost
from backend.routers.library import LibraryItemOut, clips_for_handles

router = APIRouter(dependencies=[Depends(require_api_key)])

MAX_LIMIT = 500
POSTS_LIMIT = 60


class PersonOut(BaseModel):
    key: str
    member_keys: list[str]
    sources: list[str]
    display_name: str
    sport: Optional[str]
    school: Optional[str]
    year: Optional[str]
    campus: Optional[str]
    gender: Optional[str]
    status: str
    application_status: Optional[str]
    ig_handle: Optional[str]
    followers: Optional[int]
    followers_source: Optional[str]          # 'ambassador' | 'roster' (measured) | 'application'
    followers_as_of: Optional[datetime]
    followers_self_reported: bool
    tiktok_handle: Optional[str]
    tiktok_followers: Optional[int]          # self-reported
    youtube_handle: Optional[str]
    youtube_subscribers: Optional[int]       # self-reported
    x_handle: Optional[str]
    profile_pic_url: Optional[str]
    # Admins only (directory.ADMIN_ONLY_FIELDS). Null for every other role.
    nil_deals_done: Optional[str]
    nil_deals_wanted: Optional[str]
    content_type: Optional[str]
    partner_consent: Optional[bool]
    applied_at: Optional[datetime]
    first_seen: Optional[datetime]
    collab_posts: Optional[int]              # None = unknown
    collab_views: Optional[int]
    collab_engagement: Optional[int]
    last_pulled: Optional[datetime]


class DirectoryPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PersonOut]


class FacetValue(BaseModel):
    value: str
    count: int


class FacetsOut(BaseModel):
    total: int
    sport: list[FacetValue]
    school: list[FacetValue]
    campus: list[FacetValue]
    status: list[FacetValue]


class HistoryPoint(BaseModel):
    pulled_at: Optional[datetime]
    ig_followers: Optional[int]
    tiktok_followers: Optional[int]
    youtube_subscribers: Optional[int]
    source: str                              # 'roster' | 'ambassador' | 'reported'


class PostOut(BaseModel):
    post_id: str
    account_username: Optional[str]
    description: Optional[str]
    publish_time: Optional[datetime]
    permalink: Optional[str]
    post_type: Optional[str]
    media_url: Optional[str]
    thumbnail_url: Optional[str]
    views: Optional[int]
    likes: Optional[int]
    comments: Optional[int]
    shares: Optional[int]
    saves: Optional[int]


class ApplicationPrivateOut(BaseModel):
    application_id: int
    email: str
    college_email: Optional[str]
    phone: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    status: str
    submitted_at: Optional[datetime]
    updated_at: Optional[datetime]
    roster_link: Optional[str]
    international: Optional[bool]
    instagram: Optional[str]
    instagram_followers: Optional[str]
    tiktok: Optional[str]
    tiktok_followers: Optional[str]
    youtube: Optional[str]
    youtube_subscribers: Optional[str]
    other_followers: Optional[str]
    purpose: Optional[str]
    description: Optional[str]
    answers: Optional[Any]
    consent_program_email: bool
    consent_sms: bool
    consent_marketing: bool
    consent_partners: bool
    consent_at: Optional[datetime]


class PersonDetailOut(BaseModel):
    person: PersonOut
    history: list[HistoryPoint]
    posts: list[PostOut]
    # Content library clips that tag one of their Instagram handles, newest
    # first (at most library.CLIPS_LIMIT); clips_total counts them all.
    clips: list[LibraryItemOut] = []
    clips_total: int = 0
    # Admins only. Absent (null) for every other role.
    applications: Optional[list[ApplicationPrivateOut]] = None


def is_admin(request: Request) -> bool:
    """Admin account, or a service caller (no account header) or local mode,
    which keep full access (backend/auth.py)."""
    user = getattr(request.state, "dashboard_user", None)
    return user is None or user.role == "admin"


def person_out(p: dict, admin: bool) -> PersonOut:
    out = PersonOut(**p)
    if not admin:
        for name in directory.ADMIN_ONLY_FIELDS:
            setattr(out, name, None)
    return out


def _query(
    request: Request,
    q: Optional[str] = Query(None, max_length=200, description="name, handle, school or sport contains"),
    sport: Optional[str] = Query(None, max_length=200),
    school: Optional[str] = Query(None, max_length=200),
    campus: Optional[str] = Query(None, max_length=200),
    status: Optional[str] = Query(None, description=" | ".join(directory.STATUSES)),
    source: Optional[str] = Query(None, description=" | ".join(directory.SOURCES)),
    partner_consent: Optional[bool] = Query(None),
    min_followers: Optional[int] = Query(None, ge=0),
    max_followers: Optional[int] = Query(None, ge=0),
    has_content: Optional[bool] = Query(None, description="has NIL TV collab posts"),
    include_declined: bool = Query(False, description="admins only: also list declined signups"),
    sort: str = Query("followers", description=" | ".join(directory.SORTS)),
) -> directory.Query:
    if include_declined and not is_admin(request):
        raise HTTPException(status_code=403, detail="Your account does not have access to this")
    if status is not None and status not in directory.STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {', '.join(directory.STATUSES)}")
    if source is not None and source not in directory.SOURCES:
        raise HTTPException(status_code=400, detail=f"source must be one of {', '.join(directory.SOURCES)}")
    if sort not in directory.SORTS:
        raise HTTPException(status_code=400, detail=f"sort must be one of {', '.join(directory.SORTS)}")
    return directory.Query(q=q, sport=sport, school=school, campus=campus, status=status, source=source,
                           partner_consent=partner_consent, min_followers=min_followers,
                           max_followers=max_followers, has_content=has_content,
                           include_declined=include_declined, sort=sort)


@router.get("/", response_model=DirectoryPage)
def list_people(
    request: Request,
    f: directory.Query = Depends(_query),
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    matched = directory.apply(directory.build_directory(db), f)
    return DirectoryPage(total=len(matched), limit=limit, offset=offset,
                         items=[person_out(p, is_admin(request)) for p in matched[offset:offset + limit]])


@router.get("/facets", response_model=FacetsOut)
def get_facets(
    request: Request,
    include_declined: bool = Query(False, description="admins only: count declined signups too"),
    db: Session = Depends(get_db),
):
    if include_declined and not is_admin(request):
        raise HTTPException(status_code=403, detail="Your account does not have access to this")
    people = directory.build_directory(db)
    if not include_declined:
        people = [p for p in people if not directory.is_declined(p)]
    return FacetsOut(total=len(people), **directory.facets(people))


_CSV_COLUMNS = (
    "key", "display_name", "status", "sources", "sport", "school", "year", "campus", "gender",
    "ig_handle", "followers", "followers_source", "followers_self_reported", "followers_as_of",
    "tiktok_handle", "tiktok_followers", "youtube_handle", "youtube_subscribers", "x_handle",
    "nil_deals_done", "nil_deals_wanted", "content_type", "partner_consent", "applied_at",
    "collab_posts", "collab_views", "collab_engagement", "last_pulled",
    "email", "college_email", "phone",
)


def _csv_cell(value: Any) -> Any:
    """Spreadsheets run a cell that starts with one of these as a formula, and
    the signup answers come from the public."""
    if isinstance(value, list):
        value = ",".join(str(v) for v in value)
    if isinstance(value, datetime):
        value = value.isoformat()
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return "" if value is None else value


@router.get("/export.csv")
def export_csv(request: Request, f: directory.Query = Depends(_query), db: Session = Depends(get_db)):
    """Every matching person with contact fields from their newest application.
    Admin-only here and in accounts.ADMIN_ONLY_PREFIXES."""
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="Your account does not have access to this")
    people = directory.apply(directory.build_directory(db), f)
    contacts = directory.contacts_by_application(db, [p["application_ids"][0] for p in people
                                                       if p["application_ids"]])
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(_CSV_COLUMNS)
    for p in people:
        row = {**p, **contacts.get(p["application_ids"][0] if p["application_ids"] else None, {})}
        writer.writerow([_csv_cell(row.get(c)) for c in _CSV_COLUMNS])
    return Response(content=out.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="athletes.csv"', "Cache-Control": "no-store"})


def _history(db: Session, person: dict) -> list[HistoryPoint]:
    points: list[HistoryPoint] = []
    if person["athlete_ids"]:
        for s in (db.query(AthleteSnapshot).filter(AthleteSnapshot.athlete_id.in_(person["athlete_ids"]))
                  .order_by(AthleteSnapshot.pulled_at.desc()).limit(500)):
            points.append(HistoryPoint(pulled_at=s.pulled_at, ig_followers=s.ig_followers,
                                       tiktok_followers=s.tiktok_followers, youtube_subscribers=None,
                                       source="roster"))
    if person["ambassador_ids"]:
        for s in (db.query(AmbassadorSnapshot)
                  .filter(AmbassadorSnapshot.ambassador_id.in_(person["ambassador_ids"]))
                  .order_by(AmbassadorSnapshot.pulled_at.desc()).limit(500)):
            points.append(HistoryPoint(
                pulled_at=s.pulled_at, ig_followers=s.followers, tiktok_followers=s.tiktok_followers,
                youtube_subscribers=s.youtube_subscribers,
                source="reported" if s.source == "reported" else "ambassador"))
    points.sort(key=lambda h: h.pulled_at.timestamp() if h.pulled_at else 0, reverse=True)
    return points


def _posts(db: Session, person: dict) -> list[PostOut]:
    """Their NIL TV network posts: stamped with one of their ambassador ids,
    else posted from their Instagram handle."""
    conds = []
    if person["ambassador_ids"]:
        conds.append(NiltvNetworkPost.ambassador_id.in_(person["ambassador_ids"]))
    if person["ig_handle"]:
        conds.append(func.lower(NiltvNetworkPost.account_username) == person["ig_handle"])
    if not conds:
        return []
    rows = (db.query(NiltvNetworkPost).filter(or_(*conds))
            .order_by(NiltvNetworkPost.publish_time.desc().nullslast()).limit(POSTS_LIMIT).all())
    return [PostOut(
        post_id=r.post_id, account_username=r.account_username, description=r.description,
        publish_time=r.publish_time, permalink=r.permalink, post_type=r.post_type,
        media_url=r.media_url, thumbnail_url=r.thumbnail_url, views=r.views, likes=r.likes,
        comments=r.comments, shares=r.shares, saves=r.saves,
    ) for r in rows]


@router.get("/{key}", response_model=PersonDetailOut)
def get_person(key: str, request: Request, db: Session = Depends(get_db)):
    admin = is_admin(request)
    person = directory.resolve_key(directory.build_directory(db), key)
    # A declined signup is hidden from non-admins here too, not only in the list.
    if person is None or (directory.is_declined(person) and not admin):
        raise HTTPException(status_code=404, detail="Athlete not found")
    clips_total, clips = clips_for_handles(db, person["ig_handles"])
    detail = PersonDetailOut(person=person_out(person, admin), history=_history(db, person),
                             posts=_posts(db, person), clips=clips, clips_total=clips_total)
    if admin:
        detail.applications = [ApplicationPrivateOut(**a) for a in directory.private_details(db, person)]
    return detail
