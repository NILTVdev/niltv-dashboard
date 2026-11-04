"""Community Star applications (niltv.com/communitystar).

Two routers on the same prefix (/api/community-star):

* ``public_router`` - no API key. The application form on niltv.com posts
  here (CORS-limited to the site origins, see main.py).
* ``router`` - X-API-Key like every other dashboard route. List + counts for
  staff; the staff sheet (jobs.export_community_star_sheet) is the main view.

Rules from the application form spec and the official rules: one application
per person (per email, and per Instagram account), the post link only accepts
instagram.com, the form only takes entries between the open and close times
(the server clock is the official clock). The confirmation email repeats the
confirmation screen.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth import actor_name, require_api_key
from backend.config import get_settings
from backend.database import SessionLocal, get_db
from backend.models import CommunityStarApplication
from backend.onboarding import cognito, mailer
from backend.routers.applications import _client_ip

log = logging.getLogger(__name__)

public_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_api_key)])

SEASON = "2026"
CLASS_YEARS = ("Fr", "So", "Jr", "Sr", "Grad")

# Same shape as the athlete signup's limiter: N posts per IP per window, in
# process (one uvicorn worker). Generous enough for a team applying from one
# campus network, tight enough to blunt a script.
_RATE_LIMIT = 10
_RATE_WINDOW = 3600.0
_hits: dict[str, deque] = {}
_MAX_BODY = 32 * 1024
_HONEYPOT_FIELDS = ("website",)

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
_HANDLE = re.compile(r"^[a-z0-9._]{1,30}$")
_POST = re.compile(
    r"^https?://(?:www\.|m\.)?instagram\.com/(?:[A-Za-z0-9._]+/)?(p|reel|reels|tv)/([A-Za-z0-9_-]+)/?(?:[?#].*)?$",
    re.I)

# (payload key, column, max length). Required text fields first.
_REQUIRED_TEXT = (
    ("fullName", "full_name", 120),
    ("phone", "phone", 30),
    ("school", "school", 160),
    ("sport", "sport", 80),
    ("community", "community", 160),
    # 500 characters on the form; a browser counts a line break as one and
    # may send two, so the server allows headroom.
    ("work", "work", 1000),
)
_OPTIONAL_TEXT = (
    ("organization", "organization", 160),
    ("schoolState", "school_state", 40),
    ("schoolDomain", "school_domain", 120),
    ("consentVersion", "consent_version", 40),
    ("userAgent", "user_agent", 400),
)
_REQUIRED_CHECKS = (
    ("collabInvited", "collab_invited"),
    ("eligibleAndRules", "eligible_and_rules"),
    ("confirmAge", "confirm_age"),
    ("consentPrivacy", "consent_privacy"),
)
_OPTIONAL_CHECKS = (
    ("consentEmail", "consent_email"),
    ("consentSms", "consent_sms"),
    ("consentPartners", "consent_partners"),
)


def _rate_limited(ip: str, now: Optional[float] = None) -> bool:
    now = now if now is not None else time.time()
    q = _hits.setdefault(ip, deque())
    while q and now - q[0] > _RATE_WINDOW:
        q.popleft()
    if len(q) >= _RATE_LIMIT:
        return True
    q.append(now)
    return False


def window() -> tuple[datetime, datetime]:
    s = get_settings()
    return datetime.fromisoformat(s.community_star_opens), datetime.fromisoformat(s.community_star_closes)


def is_open(now: Optional[datetime] = None) -> bool:
    opens, closes = window()
    now = now or datetime.now(tz=timezone.utc)
    return opens <= now < closes


def normalize_post(url: str) -> str:
    """instagram.com post/reel link -> https://www.instagram.com/<kind>/<code>/,
    '' when it is not one."""
    m = _POST.match(url.strip())
    if not m:
        return ""
    kind = m.group(1).lower()
    return f"https://www.instagram.com/{'reel' if kind == 'reels' else kind}/{m.group(2)}/"


def _text(payload: dict, key: str) -> str:
    v = payload.get(key)
    return v.strip() if isinstance(v, str) else ""


def parse(payload: dict) -> dict:
    """Validate the form body and map it to columns. ValueError(message) on
    the first problem; the message is safe to show."""
    row: dict = {}
    email = _text(payload, "email").lower()
    if not email or len(email) > 200 or not _EMAIL.match(email):
        raise ValueError("a valid email is required")
    row["email"] = email

    for key, col, limit in _REQUIRED_TEXT:
        v = _text(payload, key)
        if not v:
            raise ValueError(f"{key} is required")
        if len(v) > limit:
            raise ValueError(f"{key} is too long")
        row[col] = v
    for key, col, limit in _OPTIONAL_TEXT:
        v = _text(payload, key)
        row[col] = v[:limit] or None

    digits = re.sub(r"\D+", "", row["phone"])
    if not 10 <= len(digits) <= 15:
        raise ValueError("a phone number with area code is required")

    year = _text(payload, "classYear")
    if year not in CLASS_YEARS:
        raise ValueError(f"classYear must be one of {CLASS_YEARS}")
    row["class_year"] = year

    handle = _text(payload, "instagram").lstrip("@").lower()
    if not _HANDLE.match(handle):
        raise ValueError("instagram handle is not valid")
    row["instagram"] = handle

    post = normalize_post(_text(payload, "postUrl"))
    if not post:
        raise ValueError("postUrl must be an instagram.com post or reel link")
    row["post_url"] = post

    for key, col in _REQUIRED_CHECKS:
        if payload.get(key) is not True:
            raise ValueError(f"{key} must be checked")
        row[col] = True
    for key, col in _OPTIONAL_CHECKS:
        row[col] = payload.get(key) is True

    row["school_matched"] = payload.get("schoolMatched") is True
    utm = payload.get("utm")
    row["utm"] = {str(k)[:40]: str(v)[:200] for k, v in utm.items()} if isinstance(utm, dict) else None
    return row


def _confirm(app_id: int, to: str, full_name: str) -> None:
    """Background task: send the confirmation and record that it went out."""
    sent = mailer.send_community_star_received(to, full_name.split()[0] if full_name else "")
    if not sent:
        return
    db = SessionLocal()
    try:
        db.query(CommunityStarApplication).filter(CommunityStarApplication.id == app_id).update(
            {"confirmation_sent": True})
        db.commit()
    finally:
        db.close()


@public_router.post("/applications")
async def submit_application(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """The niltv.com/communitystar form. 200 {"status":"ok","id":n};
    409 the email already applied; 410 outside the application window."""
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise HTTPException(status_code=413, detail="payload too large")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="expected an object")

    # Honeypot: the form renders it hidden; a filled value is a bot. Answer
    # 200 so the script thinks it worked.
    if any(str(payload.get(f) or "").strip() for f in _HONEYPOT_FIELDS):
        return {"status": "ok"}

    if not is_open():
        raise HTTPException(status_code=410, detail="applications are closed")

    ip = _client_ip(request)
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="too many submissions, try again later")

    try:
        row = parse(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if db.query(CommunityStarApplication.id).filter(
            CommunityStarApplication.season == SEASON,
            CommunityStarApplication.email == row["email"]).first():
        raise HTTPException(status_code=409, detail="this email already has an application")
    # Official rules: one application per person. A second email with the
    # same Instagram account is the same person.
    if db.query(CommunityStarApplication.id).filter(
            CommunityStarApplication.season == SEASON,
            CommunityStarApplication.instagram == row["instagram"]).first():
        raise HTTPException(status_code=409, detail="this Instagram account already has an application")

    raw_answers = {k: v for k, v in payload.items() if k not in _HONEYPOT_FIELDS}
    app = CommunityStarApplication(season=SEASON, source="communitystar", ip=ip, answers=raw_answers, **row)
    db.add(app)
    try:
        db.commit()
    except IntegrityError:   # the same email posted twice at once
        db.rollback()
        raise HTTPException(status_code=409, detail="this email already has an application")
    db.refresh(app)
    log.info("community star application id=%s school=%s", app.id, app.school)
    background_tasks.add_task(_confirm, app.id, app.email, app.full_name)
    return {"status": "ok", "id": app.id}


def email_hint(email: str) -> str:
    """j•••@gmail.com: enough for someone to recognise their own address."""
    name, _, domain = email.partition("@")
    return f"{name[:1]}•••@{domain}"


@public_router.get("/me")
def my_application(request: Request, response: Response, db: Session = Depends(get_db)):
    """Has the signed-in visitor applied? The page uses this to show "You've
    applied" on any device. Applying never needs an account; this only reads.

    Answers for the Cognito token's own verified email and takes no email
    input, so it cannot be used to look up anyone else.
    """
    response.headers["Cache-Control"] = "no-store"
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    try:
        account = cognito.verify(token)
    except cognito.TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))
    if not account.email_verified:
        return {"applied": False}
    found = db.query(CommunityStarApplication.id).filter(
        CommunityStarApplication.season == SEASON,
        CommunityStarApplication.email == account.email).first()
    if not found:
        return {"applied": False}
    return {"applied": True, "email_hint": email_hint(account.email)}


# -- Review -----------------------------------------------------------------

# applied -> shortlist -> finalist -> top5 -> winner, or disqualified (033).
STAGES = ("applied", "shortlist", "finalist", "top5", "winner", "disqualified")
STAGE_LABELS = {"applied": "Applied", "shortlist": "Shortlist", "finalist": "Finalist",
                "top5": "Top 5", "winner": "Winner", "disqualified": "Disqualified"}
# Review fields staff may change, with their length caps (None = boolean).
REVIEW_FIELDS = {"collab_accepted": None, "stage": None, "notes": 2000,
                 "photo_url": 500, "cause": 200, "youtube_id": 20}
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_URL = re.compile(r"(?:youtu\.be/|[?&]v=|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})")


def parse_stage(value) -> Optional[str]:
    """'Top 5' / 'top5' / 'Finalists' -> a STAGES key; None when unknown."""
    key = re.sub(r"[^a-z0-9]", "", str(value or "").lower())
    key = {"": "applied", "shortlisted": "shortlist", "finalists": "finalist",
           "winners": "winner", "dq": "disqualified"}.get(key, key)
    return key if key in STAGES else None


def parse_youtube(value) -> Optional[str]:
    """A YouTube link or bare id -> the 11-character id; '' clears it."""
    v = str(value or "").strip()
    if not v:
        return ""
    if _YOUTUBE_ID.match(v):
        return v
    m = _YOUTUBE_URL.search(v)
    return m.group(1) if m else None


def apply_review(db: Session, a: CommunityStarApplication, fields: dict, by: str) -> list[str]:
    """Set review fields on one row (dashboard and sheet import share this).
    ValueError on a bad value; returns the names of the fields that changed."""
    changed = []
    for name, value in fields.items():
        if name not in REVIEW_FIELDS:
            raise ValueError(f"{name} is not a review field")
        if name == "collab_accepted":
            value = bool(value)
        elif name == "stage":
            stage = parse_stage(value)
            if stage is None:
                raise ValueError(f"stage must be one of {STAGES}")
            value = stage
        elif name == "youtube_id":
            yid = parse_youtube(value)
            if yid is None:
                raise ValueError("youtube_id must be a YouTube link or video id")
            value = yid or None
        else:
            value = (str(value).strip() if value is not None else "")[:REVIEW_FIELDS[name]] or None
        if getattr(a, name) != value:
            setattr(a, name, value)
            changed.append(name)
    if changed:
        a.reviewed_at = datetime.now(tz=timezone.utc)
        a.reviewed_by = by
    return changed


# -- Staff ------------------------------------------------------------------

def row_out(a: CommunityStarApplication) -> dict:
    return {
        "id": a.id, "season": a.season, "created_at": a.created_at,
        "full_name": a.full_name, "email": a.email, "phone": a.phone,
        "school": a.school, "school_state": a.school_state, "school_matched": a.school_matched,
        "sport": a.sport, "class_year": a.class_year,
        "instagram": a.instagram, "post_url": a.post_url,
        "community": a.community, "work": a.work, "organization": a.organization,
        "consent_email": a.consent_email, "consent_sms": a.consent_sms, "consent_partners": a.consent_partners,
        "confirmation_sent": a.confirmation_sent, "utm": a.utm,
        "collab_accepted": a.collab_accepted, "stage": a.stage, "notes": a.notes,
        "photo_url": a.photo_url, "cause": a.cause, "youtube_id": a.youtube_id,
        "reviewed_at": a.reviewed_at, "reviewed_by": a.reviewed_by,
    }


@router.get("/applications")
def list_applications(
    season: str = Query(SEASON),
    q: Optional[str] = Query(None, description="name / email / handle / school contains"),
    limit: int = Query(1000, le=5000),
    db: Session = Depends(get_db),
):
    query = db.query(CommunityStarApplication).filter(CommunityStarApplication.season == season)
    if q:
        like = f"%{q.strip().lstrip('@')}%"
        query = query.filter(
            CommunityStarApplication.full_name.ilike(like) | CommunityStarApplication.email.ilike(like)
            | CommunityStarApplication.instagram.ilike(like) | CommunityStarApplication.school.ilike(like))
    rows = query.order_by(CommunityStarApplication.created_at.desc()).limit(limit).all()
    return [row_out(a) for a in rows]


@router.post("/applications/{app_id}/update")
async def update_application(app_id: int, request: Request, db: Session = Depends(get_db)):
    """Staff review: any of collab_accepted, stage, notes, photo_url, cause,
    youtube_id. POST because the CORS config only allows GET/POST."""
    a = db.query(CommunityStarApplication).filter(CommunityStarApplication.id == app_id).first()
    if a is None:
        raise HTTPException(status_code=404, detail="application not found")
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")
    if not isinstance(body, dict) or not body:
        raise HTTPException(status_code=400, detail="expected an object of review fields")
    try:
        changed = apply_review(db, a, body, by=actor_name(request, "dashboard"))
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    db.refresh(a)
    return {"changed": changed, "application": row_out(a)}


@router.get("/summary")
def summary(season: str = Query(SEASON), db: Session = Depends(get_db)):
    rows = db.query(CommunityStarApplication.school, CommunityStarApplication.created_at,
                    CommunityStarApplication.stage, CommunityStarApplication.collab_accepted).filter(
        CommunityStarApplication.season == season).all()
    opens, closes = window()
    by_stage = {s: 0 for s in STAGES}
    for _, _, stage, _ in rows:
        by_stage[stage] = by_stage.get(stage, 0) + 1
    return {
        "season": season,
        "total": len(rows),
        "schools": len({s for s, _, _, _ in rows}),
        "collab_accepted": sum(1 for *_, c in rows if c),
        "by_stage": by_stage,
        "last_at": max((c for _, c, _, _ in rows), default=None),
        "window": {"opens": opens, "closes": closes, "open": is_open()},
    }
