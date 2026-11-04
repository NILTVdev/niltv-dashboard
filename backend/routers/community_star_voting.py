"""Community Star from the finalists to the winners (niltv.com/communitystar).

The page follows one feed, GET /api/community-star/public. Two rules hold it:

* Time alone never publishes a name. A finalist appears only after staff
  publish AND the official clock passes the finalists time. The top 5 and the
  winners appear only from staff publish actions.
* A vote counts only through POST /votes/confirm, sent by the Confirm my vote
  button. No GET changes a vote, and no setting can confirm one.

Public responses carry no email, phone, notes, IP or vote count. Counts stay on
the staff routes, which sit behind X-API-Key and are admin-only (accounts.py
lists no read prefix for /api/community-star).

Voting policy the team has not settled lives in community_star_program.settings
with the defaults in SETTINGS, not in code.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth import actor_name, require_api_key
from backend.config import get_settings
from backend.database import get_db
from backend.models import CommunityStarApplication, CommunityStarProgram, CommunityStarVote
from backend.onboarding import card_photo, vote_guard, vote_outbox
from backend.routers.applications import _client_ip
from backend.routers.community_star import SEASON, apply_review, official_now, row_out, window

log = logging.getLogger(__name__)

public_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_api_key)])

# A finalist still in the running. Disqualified rows drop out everywhere.
ACTIVE_STAGES = ("finalist", "top5", "winner")
TOP5_STAGES = ("top5", "winner")
BOARD_ROWS = 5                      # the brief: the leaderboard shows the top 5
FEED_SECONDS = 15.0

SETTINGS: dict[str, Any] = {
    "confirm_grace_minutes": 0,
    "allow_pending_change": True,
    "leaderboard_visible": True,
    "board_min_votes": 1,
    "card_order": "alphabetical",
    "voting_paused": False,
}
CARD_ORDERS = ("alphabetical", "shuffled")

_MAX_BODY = 8 * 1024
_MAX_SENDS = 3
_RESEND_SECONDS = 60
_RATE_WINDOW = 3600.0
_vote_hits: dict[str, deque] = {}

_BURST_VOTES = 10
_BURST_SECONDS = 600
_FAST_CONFIRM_SECONDS = 5
_SIMILAR_EMAILS = 3


# -- Program state ------------------------------------------------------------

def schedule() -> dict[str, datetime]:
    s = get_settings()
    opens, closes = window()
    return {
        "opens": opens, "closes": closes,
        "finalists": datetime.fromisoformat(s.community_star_finalists_at),
        "vote_opens": datetime.fromisoformat(s.community_star_vote_opens),
        "vote_closes": datetime.fromisoformat(s.community_star_vote_closes),
    }


def get_program(db: Session) -> CommunityStarProgram:
    """This season's row, created on first use."""
    p = db.get(CommunityStarProgram, SEASON)
    if p is None:
        db.execute(insert(CommunityStarProgram).values(season=SEASON).on_conflict_do_nothing())
        db.commit()
        p = db.get(CommunityStarProgram, SEASON)
    return p


def settings_of(p: CommunityStarProgram) -> dict:
    return {**SETTINGS, **(p.settings or {})}


def confirm_deadline(p: CommunityStarProgram) -> datetime:
    """When a pending vote can no longer be confirmed, and when the board freezes."""
    grace = int(settings_of(p)["confirm_grace_minutes"])
    return schedule()["vote_closes"] + timedelta(minutes=grace)


def stage_at(now: datetime, p: CommunityStarProgram) -> str:
    """The stage at ``now``. Nothing past closed happens without published
    finalists: with no names out there was no vote to close."""
    t = schedule()
    if now < t["opens"]:
        return "coming"
    if now < t["closes"]:
        return "open"
    if p.finalists_published_at is None or now < t["finalists"]:
        return "closed"
    if now >= t["vote_closes"]:
        return "winners" if _winners_on(now, p) else "top5"
    return "voting" if now >= t["vote_opens"] else "finalists"


def stage_now(db: Session) -> str:
    """The single source of truth for the stage."""
    return stage_at(official_now(db), get_program(db))


def _finalists_on(now: datetime, p: CommunityStarProgram) -> bool:
    return p.finalists_published_at is not None and now >= schedule()["finalists"]


def _top5_on(now: datetime, p: CommunityStarProgram) -> bool:
    return (_finalists_on(now, p) and p.top5_published_at is not None
            and now >= schedule()["vote_closes"])


def _winners_on(now: datetime, p: CommunityStarProgram) -> bool:
    return _top5_on(now, p) and p.winners_published_at is not None


def _votes_blocked(p: CommunityStarProgram) -> bool:
    """Paused by staff, or production with no Turnstile secret."""
    s = get_settings()
    return bool(settings_of(p)["voting_paused"]) or (s.is_production and not (s.turnstile_secret and s.turnstile_site_key))


# -- Public feed --------------------------------------------------------------

def card_name(a: CommunityStarApplication) -> str:
    return a.card_name or a.full_name


def _slug(a: CommunityStarApplication) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", card_name(a).lower()).strip("-")
    return f"{base}-{a.id}" if base else str(a.id)


def _order_key(a: CommunityStarApplication, order: str):
    if order == "shuffled":
        return hashlib.sha256(f"{a.season}:{a.id}".encode()).hexdigest()
    return (card_name(a).casefold(), a.id)


def active_finalists(db: Session) -> list[CommunityStarApplication]:
    return db.query(CommunityStarApplication).filter(
        CommunityStarApplication.season == SEASON,
        CommunityStarApplication.stage.in_(ACTIVE_STAGES)).all()


def _public_card(a: CommunityStarApplication, now: datetime, p: CommunityStarProgram) -> dict:
    return {
        "id": a.id,
        "slug": _slug(a),
        "name": card_name(a),
        "school": a.card_school or a.school,
        "sport": a.card_sport or a.sport,
        "community": a.card_community or a.community,
        "cause": a.cause or "",
        "photo": a.photo_url or "",
        "youtube": a.youtube_id or "",
        "top5": _top5_on(now, p) and a.stage in TOP5_STAGES,
        "winner": _winners_on(now, p) and a.stage == "winner",
    }


def _ranked(db: Session, finalists: list[CommunityStarApplication]) -> tuple[list[dict], int]:
    """Leaderboard rows and the confirmed total, recomputed from the vote rows.
    Rank and name only: the counts never leave this function."""
    by_id = {a.id: a for a in finalists}
    tally = db.query(
        CommunityStarVote.finalist_id, func.count(CommunityStarVote.id), func.max(CommunityStarVote.confirmed_at),
    ).filter(
        CommunityStarVote.season == SEASON, CommunityStarVote.status == "confirmed",
    ).group_by(CommunityStarVote.finalist_id).all()
    active = [(fid, n, last) for fid, n, last in tally if fid in by_id]
    active.sort(key=lambda r: (-r[1], r[2], card_name(by_id[r[0]]).casefold()))
    rows = [{"rank": i, "id": fid, "name": card_name(by_id[fid])}
            for i, (fid, _, _) in enumerate(active[:BOARD_ROWS], start=1)]
    return rows, sum(n for _, n, _ in active)


def ensure_frozen(db: Session, now: Optional[datetime] = None) -> None:
    """Store the leaderboard once, at the close plus any grace. Later voids do
    not change it. The conditional update keeps the first snapshot if two
    callers race."""
    p = get_program(db)
    now = now or official_now(db)
    if p.frozen_board is not None or not _finalists_on(now, p) or now < confirm_deadline(p):
        return
    rows, total = _ranked(db, active_finalists(db))
    board = {"rows": rows if total >= int(settings_of(p)["board_min_votes"]) else []}
    db.execute(update(CommunityStarProgram).where(
        CommunityStarProgram.season == SEASON, CommunityStarProgram.frozen_at.is_(None),
    ).values(frozen_board=board, frozen_at=datetime.now(tz=timezone.utc)))
    db.commit()
    db.refresh(p)


def _board(db: Session, now: datetime, p: CommunityStarProgram, stage: str,
           finalists: list[CommunityStarApplication]) -> dict:
    conf = settings_of(p)
    if stage not in ("voting", "top5", "winners") or not conf["leaderboard_visible"]:
        return {"state": "hidden", "rows": []}
    if now >= confirm_deadline(p) and p.frozen_board is not None:
        # A finalist disqualified after the close leaves the page. The stored
        # snapshot and the other ranks stay as they were.
        active = {a.id for a in finalists}
        return {"state": "frozen", "rows": [r for r in p.frozen_board.get("rows", []) if r["id"] in active]}
    rows, total = _ranked(db, finalists)
    if total < int(conf["board_min_votes"]) or not rows:
        return {"state": "empty", "rows": []}
    return {"state": "live", "rows": rows}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_feed(db: Session) -> dict:
    now = official_now(db)
    ensure_frozen(db, now)
    p = get_program(db)
    stage = stage_at(now, p)
    conf = settings_of(p)
    t = schedule()
    show = _finalists_on(now, p) and stage in ("finalists", "voting", "top5", "winners")
    rows = active_finalists(db) if show else []
    rows.sort(key=lambda a: _order_key(a, conf["card_order"]))
    blocked = _votes_blocked(p)
    return {
        "stage": stage,
        "times": {k: _iso(v) for k, v in t.items()},
        "voting": {"open": stage == "voting" and not blocked, "paused": blocked,
                   "turnstile": bool(get_settings().turnstile_secret),
                   "turnstile_site_key": get_settings().turnstile_site_key},
        "finalists": [_public_card(a, now, p) for a in rows],
        "board": _board(db, now, p, stage, rows),
        "top5_published": _top5_on(now, p),
        "winners_published": _winners_on(now, p),
    }


_feed_lock = threading.Lock()
_feed: dict[str, Any] = {"at": 0.0, "body": None}


def clear_feed_cache() -> None:
    _feed["body"] = None


@public_router.get("/public")
def public_feed(response: Response, db: Session = Depends(get_db)):
    """Everything the page shows. server_time stays current on a cached body,
    because the page sets its clock from it."""
    with _feed_lock:
        if _feed["body"] is None or time.monotonic() - _feed["at"] >= FEED_SECONDS:
            _feed["body"] = build_feed(db)
            _feed["at"] = time.monotonic()
        body = _feed["body"]
    response.headers["Cache-Control"] = f"public, max-age={int(FEED_SECONDS)}"
    return {"server_time": _iso(official_now(db)), **body}


# -- Voting -------------------------------------------------------------------

async def _json_body(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise HTTPException(status_code=413, detail="payload too large")
    try:
        body = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="invalid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="expected an object")
    return body


def _rate_limited(ip: str) -> bool:
    now = time.time()
    if len(_vote_hits) > 50000:
        _vote_hits.clear()
    q = _vote_hits.setdefault(ip, deque())
    while q and now - q[0] > _RATE_WINDOW:
        q.popleft()
    if len(q) >= get_settings().community_star_vote_rate_per_hour:
        return True
    q.append(now)
    return False


def _check_turnstile(token: Any, ip: str) -> None:
    s = get_settings()
    if not s.turnstile_secret:
        if s.is_production:
            raise HTTPException(status_code=503, detail="voting is not available right now")
        return
    try:
        ok = vote_guard.turnstile_ok(s.turnstile_secret, token if isinstance(token, str) else "", ip)
    except vote_guard.TurnstileUnavailable:
        raise HTTPException(status_code=503, detail="voting is not available right now, try again soon")
    if not ok:
        raise HTTPException(status_code=400, detail="we could not verify this browser, try again")


def _voter_email(value: Any) -> str:
    email = vote_guard.clean_email(value)
    if not email:
        raise HTTPException(status_code=400, detail="enter a valid email address")
    domain = email.rpartition("@")[2]
    if vote_guard.is_disposable(domain):
        raise HTTPException(status_code=400, detail="use a permanent email address, not a temporary one")
    if not vote_guard.has_mail_route(domain):
        raise HTTPException(status_code=400, detail="that email domain can't receive mail")
    return email


def _in_the_vote(db: Session, finalist_id: int) -> bool:
    return db.query(CommunityStarApplication.id).filter(
        CommunityStarApplication.id == finalist_id,
        CommunityStarApplication.stage.in_(ACTIVE_STAGES)).first() is not None


def _active_finalist(db: Session, finalist_id: Any) -> CommunityStarApplication:
    a = None
    if isinstance(finalist_id, int) and not isinstance(finalist_id, bool):
        a = db.query(CommunityStarApplication).filter(
            CommunityStarApplication.id == finalist_id, CommunityStarApplication.season == SEASON,
            CommunityStarApplication.stage.in_(ACTIVE_STAGES)).first()
    if a is None:
        raise HTTPException(status_code=400, detail="that finalist isn't in the vote")
    return a


def _requeue(vote: CommunityStarVote, now: datetime) -> None:
    """Queue a fresh mail. The old link stops working now: the outbox makes the
    new token when it sends."""
    vote.token_hash = None
    vote.token_expires = None
    vote.mail_status = "queued"
    vote.mail_attempts = 0
    vote.mail_next_at = now
    vote.mail_last_error = None


def _cast(db: Session, payload: dict, ip: str, user_agent: str, background_tasks: BackgroundTasks) -> dict:
    p = get_program(db)
    if stage_at(official_now(db), p) != "voting":
        raise HTTPException(status_code=410, detail="voting is closed")
    if settings_of(p)["voting_paused"]:
        raise HTTPException(status_code=503, detail="voting is paused, try again soon")
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="too many votes from this network, try again later")
    db.rollback()   # the checks below wait on the network; give the connection back
    _check_turnstile(payload.get("turnstileToken"), ip)
    email = _voter_email(payload.get("email"))
    finalist = _active_finalist(db, payload.get("finalistId"))

    norm = vote_guard.normalize_email(email)
    real_now = datetime.now(tz=timezone.utc)
    vote = db.query(CommunityStarVote).filter(
        CommunityStarVote.season == SEASON, CommunityStarVote.email_norm == norm).with_for_update().first()
    if vote is None:
        vote = CommunityStarVote(
            season=SEASON, finalist_id=finalist.id, email=email, email_norm=norm, ip=ip,
            user_agent=user_agent, status="pending", mail_status="queued", mail_next_at=real_now)
        db.add(vote)
    elif vote.status != "pending":
        db.rollback()
        raise HTTPException(status_code=409, detail="this email has already voted")
    else:
        recent = vote.last_sent_at and (real_now - vote.last_sent_at).total_seconds() < _RESEND_SECONDS
        pick_out = not _in_the_vote(db, vote.finalist_id)
        expired = vote.token_expires is not None and official_now(db) >= vote.token_expires
        # The cap stops mail bombing. A link that can no longer be used earns one
        # more send, so that is at most one extra mail per link lifetime.
        if recent or (vote.sends >= _MAX_SENDS and not (expired or pick_out)):
            db.rollback()
            raise HTTPException(status_code=429, detail="check your inbox and spam folder for the email we sent")
        if settings_of(p)["allow_pending_change"] or pick_out:
            vote.finalist_id = finalist.id
        vote.email = email
        _requeue(vote, real_now)
    deadline = confirm_deadline(p)
    try:
        db.flush()
        vote_id = vote.id
        db.commit()
    except IntegrityError:   # the same voter posted twice at once; the other post queued the mail
        db.rollback()
        return {"status": "pending"}
    # get_db closes after the background task, so reading an expired attribute
    # from here on would hold a pooled connection for the whole send.
    background_tasks.add_task(vote_outbox.send_one, vote_id, deadline)
    return {"status": "pending"}


@public_router.post("/votes")
def cast_vote(request: Request, background_tasks: BackgroundTasks,
              payload: dict = Depends(_json_body), db: Session = Depends(get_db)):
    """Record a pending vote and email the confirm link. It does not count yet."""
    if str(payload.get("website") or "").strip():
        return {"status": "pending"}
    return _cast(db, payload, _client_ip(request), request.headers.get("user-agent", "")[:400], background_tasks)


def _find_token(db: Session, token: Any, lock: bool = False) -> Optional[CommunityStarVote]:
    if not isinstance(token, str) or not token or len(token) > 100:
        return None
    q = db.query(CommunityStarVote).filter(
        CommunityStarVote.token_hash == vote_outbox.hash_token(token), CommunityStarVote.season == SEASON)
    return (q.with_for_update() if lock else q).first()


def _confirmable(db: Session, vote: CommunityStarVote, now: datetime, p: CommunityStarProgram) -> str:
    """'pending' when this pending vote can still be confirmed, else why not."""
    t = schedule()
    if not _finalists_on(now, p) or not t["vote_opens"] <= now < confirm_deadline(p):
        return "closed"
    if not _in_the_vote(db, vote.finalist_id):
        return "finalist_out"
    if vote.token_expires is None or now >= vote.token_expires:
        return "expired"
    return "pending"


@public_router.post("/votes/preview")
def preview_vote(body: dict = Depends(_json_body), db: Session = Depends(get_db)):
    """What a confirm link is for. The page shows this before the button.
    Never changes anything."""
    vote = _find_token(db, body.get("token"))
    if vote is None or vote.status == "void":
        return {"status": "invalid", "finalist": None}
    now = official_now(db)
    p = get_program(db)
    status = "confirmed" if vote.status == "confirmed" else _confirmable(db, vote, now, p)
    a = db.get(CommunityStarApplication, vote.finalist_id)
    named = _finalists_on(now, p) and a is not None and a.stage in ACTIVE_STAGES
    return {"status": status, "finalist": {"id": a.id, "name": card_name(a)} if named else None}


@public_router.post("/votes/confirm")
def confirm_vote(request: Request, body: dict = Depends(_json_body), db: Session = Depends(get_db)):
    """The only way a vote counts. Single use: a second press answers
    "already" and changes nothing."""
    vote = _find_token(db, body.get("token"), lock=True)
    if vote is None or vote.status == "void":
        db.rollback()
        raise HTTPException(status_code=404, detail="invalid")
    if vote.status == "confirmed":
        db.rollback()
        return {"status": "already"}
    p = get_program(db)
    status = _confirmable(db, vote, official_now(db), p)
    if status != "pending":
        db.rollback()
        raise HTTPException(status_code=410, detail=status)
    if settings_of(p)["voting_paused"]:
        db.rollback()
        raise HTTPException(status_code=503, detail="voting is paused, try again soon")
    vote.status = "confirmed"
    vote.confirmed_at = datetime.now(tz=timezone.utc)
    vote.confirm_ip = _client_ip(request)
    vote.confirm_user_agent = request.headers.get("user-agent", "")[:400]
    db.commit()
    return {"status": "confirmed"}


# -- Staff: program -----------------------------------------------------------

def _stage_counts(db: Session) -> dict:
    rows = active_finalists(db)
    return {
        "finalists": len(rows),
        "top5": sum(1 for a in rows if a.stage in TOP5_STAGES),
        "winners": sum(1 for a in rows if a.stage == "winner"),
        "missing_photo": sum(1 for a in rows if not a.photo_url),
        "missing_cause": sum(1 for a in rows if not a.cause),
        "missing_youtube": sum(1 for a in rows if not a.youtube_id),
    }


def _mail_counts(db: Session) -> dict:
    found = dict(db.query(CommunityStarVote.mail_status, func.count(CommunityStarVote.id)).filter(
        CommunityStarVote.season == SEASON).group_by(CommunityStarVote.mail_status).all())
    return {k: found.get(k, 0) for k in ("queued", "sent", "failed")}


def _readiness(counts: dict, mail: dict) -> list[dict]:
    n = counts["finalists"]
    s = get_settings()
    bot_check = bool(s.turnstile_secret and s.turnstile_site_key)
    return [
        {"key": "turnstile", "label": "Turnstile keys set", "ok": bot_check,
         "detail": None if bot_check else "Set both keys. Votes are refused in production until then."},
        {"key": "finalists", "label": "Finalists marked", "ok": n > 0, "detail": f"{n} marked"},
        {"key": "photos", "label": "Finalist photos", "ok": n > 0 and not counts["missing_photo"],
         "detail": f"{counts['missing_photo']} missing"},
        {"key": "videos", "label": "Round 2 videos", "ok": n > 0 and not counts["missing_youtube"],
         "detail": f"{counts['missing_youtube']} missing"},
        {"key": "mail", "label": "Vote mail failures", "ok": not mail["failed"], "detail": f"{mail['failed']} failed"},
    ]


def _program_out(db: Session) -> dict:
    p = get_program(db)
    now = official_now(db)
    counts = _stage_counts(db)
    return {
        "season": SEASON,
        "stage": stage_at(now, p),
        "server_time": _iso(now),
        "production": get_settings().is_production,
        "times": {k: _iso(v) for k, v in schedule().items()},
        "finalists_published_at": p.finalists_published_at,
        "top5_published_at": p.top5_published_at,
        "winners_published_at": p.winners_published_at,
        "published_by": p.published_by,
        "frozen_at": p.frozen_at,
        "dev_now": None if get_settings().is_production else p.dev_now,
        "settings": settings_of(p),
        "counts": counts,
        "readiness": _readiness(counts, _mail_counts(db)),
    }


@router.get("/program")
def program_state(db: Session = Depends(get_db)):
    ensure_frozen(db)
    return _program_out(db)


def _touch(p: CommunityStarProgram) -> None:
    p.updated_at = datetime.now(tz=timezone.utc)


@router.post("/program/publish")
def publish(request: Request, body: dict = Depends(_json_body), db: Session = Depends(get_db)):
    """Staff decide what the page shows. Publishing finalists early is fine:
    names still wait for the finalists time."""
    what, on = body.get("what"), body.get("publish")
    if what not in ("finalists", "top5", "winners") or not isinstance(on, bool):
        raise HTTPException(status_code=400, detail="what must be finalists, top5 or winners; publish true or false")
    p = get_program(db)
    now = official_now(db)
    counts = _stage_counts(db)
    if on:
        if what == "finalists" and not counts["finalists"]:
            raise HTTPException(status_code=409, detail="mark at least one finalist first")
        if what == "top5":
            if now < schedule()["vote_closes"]:
                raise HTTPException(status_code=409, detail="the top 5 can't be published before voting closes")
            if p.finalists_published_at is None:
                raise HTTPException(status_code=409, detail="publish the finalists first")
            if not counts["top5"]:
                raise HTTPException(status_code=409, detail="mark the top 5 first")
        if what == "winners":
            if p.top5_published_at is None:
                raise HTTPException(status_code=409, detail="publish the top 5 first")
            if not counts["winners"]:
                raise HTTPException(status_code=409, detail="mark at least one winner first")
    else:
        if what == "finalists" and p.top5_published_at is not None:
            raise HTTPException(status_code=409, detail="unpublish the top 5 first")
        if what == "top5" and p.winners_published_at is not None:
            raise HTTPException(status_code=409, detail="unpublish the winners first")
    setattr(p, f"{what}_published_at", datetime.now(tz=timezone.utc) if on else None)
    p.published_by = actor_name(request, "dashboard")
    _touch(p)
    db.commit()
    clear_feed_cache()
    log.info("community star %s %s by %s", what, "published" if on else "unpublished", p.published_by)
    return _program_out(db)


def _setting(key: str, value: Any) -> Any:
    if key not in SETTINGS:
        raise ValueError(f"{key} is not a setting")
    if key in ("allow_pending_change", "leaderboard_visible", "voting_paused"):
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
    elif key == "card_order":
        if value not in CARD_ORDERS:
            raise ValueError(f"card_order must be one of {CARD_ORDERS}")
    else:
        low, high = (0, 1440) if key == "confirm_grace_minutes" else (1, 100000)
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            raise ValueError(f"{key} must be a whole number from {low} to {high}")
    return value


@router.post("/program/settings")
def save_settings(body: dict = Depends(_json_body), db: Session = Depends(get_db)):
    if not body:
        raise HTTPException(status_code=400, detail="expected settings")
    try:
        changes = {k: _setting(k, v) for k, v in body.items()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    p = get_program(db)
    if "confirm_grace_minutes" in changes and p.frozen_at is not None:
        raise HTTPException(status_code=409, detail="the board is frozen, so the grace period can't change")
    p.settings = {**(p.settings or {}), **changes}
    _touch(p)
    db.commit()
    clear_feed_cache()
    return _program_out(db)


@router.post("/program/dev-clock")
def dev_clock(body: dict = Depends(_json_body), db: Session = Depends(get_db)):
    """Rehearse the stages off production. {"now": iso} or {"now": null}."""
    if get_settings().is_production:
        raise HTTPException(status_code=403, detail="the dev clock is off in production")
    raw = body.get("now")
    when = None
    if raw is not None:
        try:
            when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="now must be an ISO time or null")
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
    p = get_program(db)
    p.dev_now = when
    if (when or datetime.now(tz=timezone.utc)) < confirm_deadline(p):
        # Rehearsing back before the close: the next close freezes again.
        p.frozen_board = None
        p.frozen_at = None
    _touch(p)
    db.commit()
    clear_feed_cache()
    return _program_out(db)


# -- Staff: votes -------------------------------------------------------------

def vote_tallies(db: Session) -> list[dict]:
    """Per finalist counts, most confirmed first. Staff only."""
    counts: dict[int, dict] = defaultdict(lambda: {"confirmed": 0, "pending": 0, "void": 0})
    for fid, status, n in db.query(
            CommunityStarVote.finalist_id, CommunityStarVote.status, func.count(CommunityStarVote.id),
    ).filter(CommunityStarVote.season == SEASON).group_by(
            CommunityStarVote.finalist_id, CommunityStarVote.status).all():
        counts[fid][status] = n
    rows = {a.id: a for a in active_finalists(db)}
    missing = set(counts) - set(rows)
    if missing:   # disqualified after votes came in: staff still see those votes
        rows.update({a.id: a for a in db.query(CommunityStarApplication).filter(
            CommunityStarApplication.id.in_(missing)).all()})
    out = [{"id": a.id, "name": card_name(a), "school": a.card_school or a.school, "stage": a.stage, **counts[a.id]}
           for a in rows.values()]
    out.sort(key=lambda r: (-r["confirmed"], r["name"].casefold()))
    return out


def _vote_flags(votes: list[CommunityStarVote]) -> list[dict]:
    """Hints for a human. Nothing is voided on its own."""
    flags = []
    live = [v for v in votes if v.status != "void"]

    by_ip: dict[str, list[CommunityStarVote]] = defaultdict(list)
    for v in live:
        if v.ip:
            by_ip[v.ip].append(v)
    for ip, group in by_ip.items():
        group.sort(key=lambda v: v.created_at)
        for i in range(len(group) - _BURST_VOTES + 1):
            if (group[i + _BURST_VOTES - 1].created_at - group[i].created_at).total_seconds() <= _BURST_SECONDS:
                flags.append({"kind": "ip_burst", "label": f"{len(group)} votes from {ip}, with a burst",
                              "vote_ids": [v.id for v in group]})
                break

    fast = [v.id for v in live if v.confirmed_at and v.last_sent_at
            and (v.confirmed_at - v.last_sent_at).total_seconds() < _FAST_CONFIRM_SECONDS]
    if fast:
        flags.append({"kind": "fast_confirm",
                      "label": f"Confirmed under {_FAST_CONFIRM_SECONDS} seconds after the email", "vote_ids": fast})

    similar: dict[str, list[CommunityStarVote]] = defaultdict(list)
    for v in live:
        local, _, domain = v.email_norm.partition("@")
        similar[f"{re.sub(r'[0-9._-]+$', '', local)}@{domain}"].append(v)
    for stem, group in similar.items():
        if len(group) >= _SIMILAR_EMAILS:
            flags.append({"kind": "similar_email", "label": f"{len(group)} similar addresses like {stem}",
                          "vote_ids": [v.id for v in group]})
    return flags


@router.get("/votes/summary")
def votes_summary(db: Session = Depends(get_db)):
    votes = db.query(CommunityStarVote).filter(CommunityStarVote.season == SEASON).all()
    return {
        "finalists": vote_tallies(db),
        "totals": {k: sum(1 for v in votes if v.status == k) for k in ("confirmed", "pending", "void")},
        "mail": _mail_counts(db),
        "flags": _vote_flags(votes),
    }


def _vote_out(v: CommunityStarVote, name: str) -> dict:
    return {
        "id": v.id, "finalist_id": v.finalist_id, "finalist_name": name, "email": v.email, "status": v.status,
        "void_reason": v.void_reason, "voided_by": v.voided_by, "voided_at": v.voided_at,
        "restored_by": v.restored_by, "restored_at": v.restored_at,
        "sends_reset_by": v.sends_reset_by, "sends_reset_at": v.sends_reset_at,
        "ip": v.ip, "user_agent": v.user_agent, "confirm_ip": v.confirm_ip,
        "confirm_user_agent": v.confirm_user_agent,
        "created_at": v.created_at, "confirmed_at": v.confirmed_at,
        "mail_status": v.mail_status, "mail_attempts": v.mail_attempts, "mail_last_error": v.mail_last_error,
        "sends": v.sends, "last_sent_at": v.last_sent_at,
    }


def _vote_rows(db: Session, status: Optional[str], finalist_id: Optional[int], limit: Optional[int]) -> list[dict]:
    q = db.query(CommunityStarVote, CommunityStarApplication).join(
        CommunityStarApplication, CommunityStarApplication.id == CommunityStarVote.finalist_id,
    ).filter(CommunityStarVote.season == SEASON)
    if status:
        q = q.filter(CommunityStarVote.status == status)
    if finalist_id is not None:
        q = q.filter(CommunityStarVote.finalist_id == finalist_id)
    q = q.order_by(CommunityStarVote.created_at.desc(), CommunityStarVote.id.desc())
    if limit is not None:
        q = q.limit(limit)
    return [_vote_out(v, card_name(a)) for v, a in q.all()]


@router.get("/votes")
def list_votes(
    status: Optional[str] = Query(None, pattern="^(pending|confirmed|void)$"),
    finalist_id: Optional[int] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    return _vote_rows(db, status, finalist_id, limit)


_CSV_COLUMNS = ("id", "finalist_id", "finalist_name", "email", "status", "created_at", "confirmed_at",
                "void_reason", "voided_by", "voided_at", "restored_by", "restored_at", "ip", "confirm_ip",
                "user_agent", "confirm_user_agent", "mail_status", "mail_attempts", "sends", "last_sent_at",
                "sends_reset_by", "sends_reset_at")


def _csv_cell(value: Any) -> Any:
    """Spreadsheets run a cell that starts with one of these as a formula, and
    the email and user agent come from the public."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return "" if value is None else value


@router.get("/votes.csv")
def votes_csv(db: Session = Depends(get_db)):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(_CSV_COLUMNS)
    for row in _vote_rows(db, None, None, None):
        writer.writerow([_csv_cell(row[c]) for c in _CSV_COLUMNS])
    return Response(content=out.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="community-star-votes.csv"', "Cache-Control": "no-store"})


def _locked_vote(db: Session, vote_id: int) -> CommunityStarVote:
    vote = db.query(CommunityStarVote).filter(
        CommunityStarVote.id == vote_id, CommunityStarVote.season == SEASON).with_for_update().first()
    if vote is None:
        raise HTTPException(status_code=404, detail="vote not found")
    return vote


@router.post("/votes/{vote_id}/void")
def void_vote(vote_id: int, request: Request, body: dict = Depends(_json_body), db: Session = Depends(get_db)):
    """Rule 9: staff void a bad vote, with a reason. Reversible."""
    reason = str(body.get("reason") or "").strip()[:500]
    if not reason:
        raise HTTPException(status_code=400, detail="a reason is required")
    vote = _locked_vote(db, vote_id)
    if vote.status == "void":
        db.rollback()
        raise HTTPException(status_code=409, detail="this vote is already void")
    vote.status = "void"
    vote.void_reason = reason
    vote.voided_by = actor_name(request, "dashboard")
    vote.voided_at = datetime.now(tz=timezone.utc)
    db.commit()
    clear_feed_cache()
    a = db.get(CommunityStarApplication, vote.finalist_id)
    return _vote_out(vote, card_name(a))


@router.post("/votes/{vote_id}/restore")
def restore_vote(vote_id: int, request: Request, db: Session = Depends(get_db)):
    """Undo a void. The vote returns to what it was, and the void stays on
    record beside who restored it."""
    vote = _locked_vote(db, vote_id)
    if vote.status != "void":
        db.rollback()
        raise HTTPException(status_code=409, detail="this vote is not void")
    vote.status = "confirmed" if vote.confirmed_at else "pending"
    vote.restored_by = actor_name(request, "dashboard")
    vote.restored_at = datetime.now(tz=timezone.utc)
    db.commit()
    clear_feed_cache()
    a = db.get(CommunityStarApplication, vote.finalist_id)
    return _vote_out(vote, card_name(a))


@router.post("/votes/{vote_id}/reset-sends")
def reset_sends(vote_id: int, request: Request, db: Session = Depends(get_db)):
    """Give a voter who hit the send cap their resends back. It sends nothing
    and confirms nothing: the voter still votes again and presses the button."""
    vote = _locked_vote(db, vote_id)
    if vote.status != "pending":
        db.rollback()
        raise HTTPException(status_code=409, detail="only a pending vote has sends to reset")
    vote.sends = 0
    vote.sends_reset_by = actor_name(request, "dashboard")
    vote.sends_reset_at = datetime.now(tz=timezone.utc)
    db.commit()
    a = db.get(CommunityStarApplication, vote.finalist_id)
    return _vote_out(vote, card_name(a))


# -- Staff: card photo --------------------------------------------------------

@router.post("/applications/{app_id}/photo")
def upload_photo(app_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    a = db.get(CommunityStarApplication, app_id)
    if a is None:
        raise HTTPException(status_code=404, detail="application not found")
    data = file.file.read(card_photo.MAX_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="choose a photo to upload")
    try:
        webp = card_photo.to_card_webp(data)
    except card_photo.PhotoError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        url = card_photo.upload(a.id, webp)
    except Exception as e:  # noqa: BLE001 - boto raises a wide family of errors
        log.error("community star photo upload failed id=%s err=%s", a.id, type(e).__name__)
        raise HTTPException(status_code=502, detail="the photo could not be stored, try again")
    apply_review(db, a, {"photo_url": url}, by=actor_name(request, "dashboard"))
    db.commit()
    db.refresh(a)
    clear_feed_cache()
    return {"photo_url": url, "application": row_out(a)}
