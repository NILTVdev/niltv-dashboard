"""Athlete Content Hub: the staff side (migrations 032, 033).

Staff post content asks, see who claimed each one and the link they
submitted, and approve submissions. Approved claims are what admin pays
out later. X-API-Key like every other dashboard route; backend.accounts
keeps it admin-only until a staff role exists.

The athlete side (browse, claim, submit) is a separate router signed in
with the site account, not the dashboard key.

Mutations are POST because the CORS config only allows GET/POST.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session, joinedload

from backend.auth import actor_name, require_api_key
from backend.database import get_db
from backend.models import HubAsk, HubClaim

router = APIRouter(dependencies=[Depends(require_api_key)])

ASK_STATUSES = ("draft", "open", "closed")
# Claims that hold a spot; a released claim gives its spot back.
_HOLDING = ("claimed", "submitted", "approved")


# -- Shapes -----------------------------------------------------------------

class AskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: Optional[str] = Field(None, max_length=60)
    format: Optional[str] = Field(None, max_length=60)
    tags: list[str] = []
    summary: Optional[str] = Field(None, max_length=2000)
    steps: list[str] = []
    due_on: Optional[date] = None
    slots: Optional[int] = Field(None, gt=0)       # None = open to all athletes
    status: str = "open"                            # 'draft' keeps it off the athlete hub

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("title is required")
        return v

    @field_validator("category", "format", "summary")
    @classmethod
    def _strip(cls, v):
        if v is None:
            return v
        v = v.strip()
        return v or None

    @field_validator("tags")
    @classmethod
    def _tags(cls, v):
        # Lower-case, trimmed, no repeats, in the order given.
        out: list[str] = []
        for t in v:
            t = t.strip().lower()
            if t and t not in out:
                out.append(t[:40])
        return out

    @field_validator("steps")
    @classmethod
    def _steps(cls, v):
        return [s.strip() for s in v if s.strip()]

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v not in ("draft", "open"):
            raise ValueError("status must be 'draft' or 'open'")
        return v


class AskOut(BaseModel):
    id: int
    title: str
    category: Optional[str]
    format: Optional[str]
    tags: list[str]
    summary: Optional[str]
    steps: list[str]
    due_on: Optional[date]
    slots: Optional[int]
    status: str
    created_by: Optional[str]
    created_at: datetime
    closed_at: Optional[datetime]
    claimed: int          # claims currently 'claimed'
    submitted: int        # waiting for approval
    approved: int
    spots_left: Optional[int]   # None = no limit


class ClaimOut(BaseModel):
    id: int
    ask_id: int
    ask_title: str
    application_id: int
    athlete_name: str
    school: Optional[str]
    sport: Optional[str]
    status: str
    claimed_at: datetime
    submitted_at: Optional[datetime]
    link: Optional[str]          # the current submitted link
    note: Optional[str]
    reviewed_at: Optional[datetime]
    reviewed_by: Optional[int]


class AskDetailOut(AskOut):
    claims: list[ClaimOut] = []


# -- Helpers ----------------------------------------------------------------

def _ask_out(ask: HubAsk) -> AskOut:
    counts = {s: 0 for s in _HOLDING}
    for c in ask.claims:
        if c.status in counts:
            counts[c.status] += 1
    held = sum(counts.values())
    return AskOut(
        id=ask.id, title=ask.title, category=ask.category, format=ask.format,
        tags=list(ask.tags or []), summary=ask.summary, steps=list(ask.steps or []),
        due_on=ask.due_on, slots=ask.slots, status=ask.status,
        created_by=ask.created_by, created_at=ask.created_at, closed_at=ask.closed_at,
        claimed=counts["claimed"], submitted=counts["submitted"], approved=counts["approved"],
        spots_left=None if ask.slots is None else max(ask.slots - held, 0),
    )


def _claim_out(claim: HubClaim) -> ClaimOut:
    app = claim.application
    current = next((s for s in reversed(claim.submissions) if s.replaced_at is None), None)
    name = " ".join(p for p in (app.first_name, app.last_name) if p) or app.email
    return ClaimOut(
        id=claim.id, ask_id=claim.ask_id, ask_title=claim.ask.title,
        application_id=claim.application_id, athlete_name=name,
        school=app.university, sport=app.sport, status=claim.status,
        claimed_at=claim.claimed_at, submitted_at=claim.submitted_at,
        link=current.url if current else None, note=current.note if current else None,
        reviewed_at=claim.reviewed_at, reviewed_by=claim.reviewed_by,
    )


def _get_ask(db: Session, ask_id: int) -> HubAsk:
    ask = db.query(HubAsk).options(joinedload(HubAsk.claims)).filter(HubAsk.id == ask_id).first()
    if ask is None:
        raise HTTPException(status_code=404, detail="Ask not found")
    return ask


# -- Asks -------------------------------------------------------------------

@router.get("/asks", response_model=list[AskOut])
def list_asks(
    status: str = Query("active", description="'active' (draft + open), one of draft/open/closed, or 'all'"),
    tag: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(HubAsk).options(joinedload(HubAsk.claims))
    if status == "active":
        q = q.filter(HubAsk.status.in_(("draft", "open")))
    elif status in ASK_STATUSES:
        q = q.filter(HubAsk.status == status)
    elif status != "all":
        raise HTTPException(status_code=400, detail=f"status must be one of {ASK_STATUSES + ('active', 'all')}")
    if tag:
        q = q.filter(HubAsk.tags.any(tag.strip().lower()))
    asks = q.order_by(HubAsk.due_on.asc().nulls_last(), HubAsk.id.desc()).all()
    return [_ask_out(a) for a in asks]


@router.post("/asks", response_model=AskOut, status_code=201)
def create_ask(payload: AskIn, request: Request, db: Session = Depends(get_db)):
    ask = HubAsk(**payload.model_dump(), created_by=actor_name(request))
    db.add(ask)
    db.commit()
    return _ask_out(_get_ask(db, ask.id))


@router.get("/asks/{ask_id}", response_model=AskDetailOut)
def get_ask(ask_id: int, db: Session = Depends(get_db)):
    ask = _get_ask(db, ask_id)
    out = AskDetailOut(**_ask_out(ask).model_dump())
    out.claims = [_claim_out(c) for c in sorted(ask.claims, key=lambda c: c.claimed_at) if c.status != "released"]
    return out


@router.post("/asks/{ask_id}/close", response_model=AskOut)
def close_ask(ask_id: int, db: Session = Depends(get_db)):
    """Stop new claims. Existing claims stay and can still be submitted and approved."""
    ask = _get_ask(db, ask_id)
    if ask.status != "closed":
        now = datetime.now(tz=timezone.utc)
        ask.status = "closed"
        ask.closed_at = now
        ask.updated_at = now
        db.commit()
    return _ask_out(_get_ask(db, ask_id))


# -- Claims -----------------------------------------------------------------

@router.get("/claims", response_model=list[ClaimOut])
def list_claims(
    status: str = Query("submitted", description="one of claimed/submitted/approved, or 'all'"),
    db: Session = Depends(get_db),
):
    """Default is the approval queue: everything submitted and not yet approved."""
    q = db.query(HubClaim).options(
        joinedload(HubClaim.ask), joinedload(HubClaim.application), joinedload(HubClaim.submissions))
    if status == "all":
        q = q.filter(HubClaim.status.in_(_HOLDING))
    elif status in _HOLDING:
        q = q.filter(HubClaim.status == status)
    else:
        raise HTTPException(status_code=400, detail=f"status must be one of {_HOLDING + ('all',)}")
    claims = q.order_by(HubClaim.submitted_at.asc().nulls_last(), HubClaim.id).all()
    return [_claim_out(c) for c in claims]


@router.post("/claims/{claim_id}/approve", response_model=ClaimOut)
def approve_claim(claim_id: int, request: Request, db: Session = Depends(get_db)):
    claim = db.query(HubClaim).filter(HubClaim.id == claim_id).first()
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    if claim.status != "submitted":
        raise HTTPException(status_code=409, detail=f"Only a submitted claim can be approved (this one is {claim.status})")
    user = getattr(request.state, "dashboard_user", None)
    claim.status = "approved"
    claim.reviewed_at = datetime.now(tz=timezone.utc)
    claim.reviewed_by = user.id if user is not None else None
    db.commit()
    db.refresh(claim)
    return _claim_out(claim)
