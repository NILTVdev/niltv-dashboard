"""Athlete Content Hub: the athlete side (migrations 035, 036).

The niltv.com /hub/ page calls these with the site account's ID token as
``Authorization: Bearer <jwt>``; there is no API key. The token's verified
email finds the athlete's applications row, and only an athlete who has
signed the athlete agreement may use the hub. Every call answers for that
athlete alone and takes no athlete id, so nobody can act as someone else.

The shapes match the contract written at the top of the hub page script:

  GET  asks               -> {asks: [...]}, each with ``mine``: null or
                             {status, claimed_at, submitted_at, url, note}
  POST asks/{id}/claim    -> 409 when the last spot has gone
  POST asks/{id}/unclaim
  POST asks/{id}/submit   -> body {url, note}; a second submit replaces the first

Mutations are POST because the CORS config only allows GET/POST.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Application, HubAsk, HubClaim, HubSubmission
from backend.onboarding import cognito

router = APIRouter()

# Onboarding statuses from a signed athlete agreement onwards.
ATHLETE_STATUSES = ("signed", "stripe_pending", "accepted")
# Claims that hold a spot; a released claim gives its spot back.
_HOLDING = ("claimed", "submitted", "approved")
NOTE_MAX = 200
URL_MAX = 2000
_HOST = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$", re.I)


# -- Who is calling ---------------------------------------------------------

def current_athlete(request: Request, response: Response, db: Session = Depends(get_db)) -> Application:
    """The signed-in athlete's applications row, or 401/403."""
    response.headers["Cache-Control"] = "no-store"
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    try:
        account = cognito.verify(token)
    except cognito.TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))
    if not account.email_verified:
        raise HTTPException(status_code=403, detail="Verify your email to use the Content Hub")
    app = db.query(Application).filter(
        func.lower(Application.email) == account.email,
        Application.status.in_(ATHLETE_STATUSES)).first()
    if app is None:
        raise HTTPException(status_code=403, detail="The Content Hub is for NIL TV athletes")
    request.state.account_sub = account.sub
    return app


# -- Shapes -----------------------------------------------------------------

class SubmitIn(BaseModel):
    url: str = Field(max_length=URL_MAX)
    note: Optional[str] = Field(None, max_length=NOTE_MAX)

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        # Same rule as the page: http(s), no spaces, a host with a dot in it.
        v = v.strip()
        if v and not re.match(r"^https?://", v, re.I):
            v = "https://" + v
        p = urlparse(v)
        if not v or re.search(r"\s", v) or p.scheme not in ("http", "https") or not _HOST.match(p.hostname or ""):
            raise ValueError("enter a link that starts with http:// or https://")
        return v

    @field_validator("note")
    @classmethod
    def _note(cls, v):
        if v is None:
            return v
        return v.strip() or None


def _mine(claim: Optional[HubClaim]) -> Optional[dict]:
    if claim is None or claim.status == "released":
        return None
    current = next((s for s in reversed(claim.submissions) if s.replaced_at is None), None)
    return {
        "status": claim.status,
        "claimed_at": claim.claimed_at,
        "submitted_at": claim.submitted_at,
        "url": current.url if current else None,
        "note": current.note if current else None,
    }


def _ask_out(ask: HubAsk, held: int, claim: Optional[HubClaim]) -> dict:
    return {
        "id": ask.id,
        "category": ask.category,
        "format": ask.format,
        "tags": list(ask.tags or []),
        "title": ask.title,
        "summary": ask.summary,
        "steps": list(ask.steps or []),
        "due": ask.due_on,
        "slots": ask.slots,
        "claimed": held,
        "posted": ask.created_at.date() if ask.created_at else None,
        "status": ask.status,
        "mine": _mine(claim),
    }


def _held(db: Session, ask_ids: list[int]) -> dict[int, int]:
    rows = (db.query(HubClaim.ask_id, func.count(HubClaim.id))
            .filter(HubClaim.ask_id.in_(ask_ids), HubClaim.status.in_(_HOLDING))
            .group_by(HubClaim.ask_id).all())
    return dict(rows)


def _my_claim(db: Session, ask_id: int, athlete: Application) -> Optional[HubClaim]:
    return db.query(HubClaim).filter(
        HubClaim.ask_id == ask_id, HubClaim.application_id == athlete.id).first()


def _one(db: Session, ask: HubAsk, athlete: Application) -> dict:
    return _ask_out(ask, _held(db, [ask.id]).get(ask.id, 0), _my_claim(db, ask.id, athlete))


# -- Routes -----------------------------------------------------------------

@router.get("/asks")
def list_asks(athlete: Application = Depends(current_athlete), db: Session = Depends(get_db)):
    """Every open ask, plus any closed one the athlete still holds a claim
    on, so My Claims keeps showing it after staff close the ask."""
    mine = {c.ask_id: c for c in db.query(HubClaim).filter(
        HubClaim.application_id == athlete.id, HubClaim.status.in_(_HOLDING))}
    asks = db.query(HubAsk).filter(
        (HubAsk.status == "open") | ((HubAsk.status == "closed") & HubAsk.id.in_(list(mine) or [0]))
    ).order_by(HubAsk.due_on.asc().nulls_last(), HubAsk.id.desc()).all()
    held = _held(db, [a.id for a in asks])
    return {"asks": [_ask_out(a, held.get(a.id, 0), mine.get(a.id)) for a in asks]}


@router.post("/asks/{ask_id}/claim")
def claim_ask(ask_id: int, request: Request, athlete: Application = Depends(current_athlete),
              db: Session = Depends(get_db)):
    # Lock the ask row so two athletes can't both take the last spot.
    ask = db.query(HubAsk).filter(HubAsk.id == ask_id).with_for_update().first()
    if ask is None or ask.status == "draft":
        raise HTTPException(status_code=404, detail="Ask not found")
    claim = _my_claim(db, ask_id, athlete)
    if claim is not None and claim.status in _HOLDING:
        db.rollback()
        return _one(db, ask, athlete)              # already claimed: nothing to do
    if ask.status != "open":
        raise HTTPException(status_code=409, detail="This ask is closed")
    if ask.slots is not None and _held(db, [ask_id]).get(ask_id, 0) >= ask.slots:
        raise HTTPException(status_code=409, detail="All spots on this ask have been claimed")
    now = datetime.now(tz=timezone.utc)
    if claim is None:
        claim = HubClaim(ask_id=ask_id, application_id=athlete.id)
        db.add(claim)
    claim.status = "claimed"                        # a re-claim reuses the released row
    claim.claimed_at = now
    claim.released_at = None
    claim.submitted_at = None
    claim.account_sub = getattr(request.state, "account_sub", None)
    db.commit()
    return _one(db, ask, athlete)


@router.post("/asks/{ask_id}/unclaim")
def unclaim_ask(ask_id: int, athlete: Application = Depends(current_athlete), db: Session = Depends(get_db)):
    ask = db.query(HubAsk).filter(HubAsk.id == ask_id).first()
    if ask is None:
        raise HTTPException(status_code=404, detail="Ask not found")
    claim = _my_claim(db, ask_id, athlete)
    if claim is None or claim.status == "released":
        return _one(db, ask, athlete)              # nothing held: nothing to do
    if claim.status == "approved":
        raise HTTPException(status_code=409, detail="This submission is approved and can't be unclaimed")
    claim.status = "released"
    claim.released_at = datetime.now(tz=timezone.utc)
    db.commit()
    return _one(db, ask, athlete)


@router.post("/asks/{ask_id}/submit")
def submit_link(ask_id: int, payload: SubmitIn, athlete: Application = Depends(current_athlete),
                db: Session = Depends(get_db)):
    """One link per claim: a new submit marks the previous link replaced."""
    ask = db.query(HubAsk).filter(HubAsk.id == ask_id).first()
    if ask is None:
        raise HTTPException(status_code=404, detail="Ask not found")
    claim = _my_claim(db, ask_id, athlete)
    if claim is None or claim.status == "released":
        raise HTTPException(status_code=409, detail="Claim this ask before submitting a link")
    if claim.status == "approved":
        raise HTTPException(status_code=409, detail="This submission is already approved")
    now = datetime.now(tz=timezone.utc)
    for s in claim.submissions:
        if s.replaced_at is None:
            s.replaced_at = now
    db.add(HubSubmission(claim_id=claim.id, url=payload.url, note=payload.note, submitted_at=now))
    claim.status = "submitted"
    claim.submitted_at = now
    db.commit()
    db.refresh(claim)
    return _one(db, ask, athlete)
