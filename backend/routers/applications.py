"""Athlete applications + onboarding pipeline.

Two routers on the same prefix (/api/applications):

* ``public_router`` - no API key. The signup form on niltv.com posts here
  (CORS-limited to the site origins), and DocuSign Connect / Stripe post
  their webhooks here (HMAC-verified). Mounted FIRST so ``/webhooks/...``
  is matched before the admin ``/{application_id}`` routes.
* ``router`` - X-API-Key like every other dashboard route. Roster list,
  detail with timeline + progress, approve / decline / resend / refresh.

Mutations are POST because the CORS config only allows GET/POST.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.auth import require_api_key
from backend.database import get_db
from backend.models import Application
from backend.onboarding import cognito, docusign, pipeline, schools, stripe_connect

log = logging.getLogger(__name__)

public_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_api_key)])

# -- Public intake ----------------------------------------------------------

# Very small in-process rate limit for the public form: N posts per IP per
# window. The box runs one uvicorn worker, so a dict is enough; the goal is
# to blunt a script, not to be a WAF.
_RATE_LIMIT = 8
_RATE_WINDOW = 3600.0
_hits: dict[str, deque] = {}
_MAX_BODY = 64 * 1024
_HONEYPOT_FIELDS = ("website", "company", "fax")


# nginx appends the connecting address to X-Forwarded-For, so the trusted value
# is the LAST hop; earlier entries are whatever the caller sent. TRUSTED_PROXY_HOPS
# (default 1) picks it; set 2 when a CDN sits in front of nginx.
_TRUSTED_HOPS = max(1, int(os.environ.get("TRUSTED_PROXY_HOPS", "1")))


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        hops = [h.strip() for h in fwd.split(",") if h.strip()]
        if len(hops) >= _TRUSTED_HOPS:
            return hops[-_TRUSTED_HOPS]
    return request.client.host if request.client else "?"


def _rate_limited(ip: str, now: Optional[float] = None) -> bool:
    now = now if now is not None else time.time()
    q = _hits.setdefault(ip, deque())
    while q and now - q[0] > _RATE_WINDOW:
        q.popleft()
    if len(q) >= _RATE_LIMIT:
        return True
    q.append(now)
    return False


@public_router.post("/")
async def submit_application(request: Request, db: Session = Depends(get_db)):
    """The niltv.com signup form. Body = the flat JSON the form builds
    (camelCase keys, see pipeline.FIELD_MAP). 200 {"status":"ok","id":n}."""
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise HTTPException(status_code=413, detail="payload too large")
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="expected an object")

    # Honeypot: the form renders these hidden; a filled value is a bot.
    # Answer 200 so the script thinks it worked.
    if any(str(payload.get(f) or "").strip() for f in _HONEYPOT_FIELDS):
        return {"status": "ok"}

    ip = _client_ip(request)
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="too many submissions, try again later")

    # Site account required (spam guard) once COGNITO_USER_POOLS is set: the
    # account's email is the application email, whatever the body says.
    if cognito.required():
        auth = request.headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        try:
            account = cognito.verify(token)
        except cognito.TokenError as e:
            raise HTTPException(status_code=401, detail=str(e))
        payload["email"] = account.email
        payload["account"] = {"sub": account.sub, "emailVerified": account.email_verified, "pool": account.pool_id}

    try:
        app, created = pipeline.intake(db, payload, ip=ip)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "id": app.id, "created": created}


# -- Webhooks ---------------------------------------------------------------

@public_router.post("/webhooks/docusign")
async def docusign_connect(
    request: Request,
    db: Session = Depends(get_db),
    sig1: Optional[str] = Header(None, alias="X-DocuSign-Signature-1"),
    sig2: Optional[str] = Header(None, alias="X-DocuSign-Signature-2"),
):
    raw = await request.body()
    if not (docusign.verify_connect_signature(raw, sig1) or docusign.verify_connect_signature(raw, sig2)):
        raise HTTPException(status_code=401, detail="bad signature")
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")
    event = docusign.parse_connect_event(body)
    app = pipeline.find_by_envelope(db, event.get("envelope_id"), event.get("signer_email"),
                                    event.get("custom_fields"))
    if app is None:
        # Not ours (another template, a test envelope). Ack so Connect stops retrying.
        log.info("docusign connect: no application for envelope %s (%s)",
                 event.get("envelope_id"), event.get("signer_email"))
        return {"status": "ignored"}
    result = pipeline.on_envelope_event(db, app, event)
    return {"status": "ok", "application_id": app.id, **result}


@public_router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
):
    raw = await request.body()
    if not stripe_connect.verify_webhook_signature(raw, stripe_signature):
        raise HTTPException(status_code=401, detail="bad signature")
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")
    if body.get("type") != "account.updated":
        return {"status": "ignored", "type": body.get("type")}
    account = (body.get("data") or {}).get("object") or {}
    acct_id = account.get("id")
    app = db.query(Application).filter(Application.stripe_account_id == acct_id).first() if acct_id else None
    if app is None:
        return {"status": "ignored", "account": acct_id}
    result = pipeline.on_stripe_account(db, app, account, actor="stripe")
    return {"status": "ok", "application_id": app.id, **result}


# -- Admin ------------------------------------------------------------------

class EventOut(BaseModel):
    at: Optional[datetime]
    kind: str
    actor: Optional[str]
    detail: Optional[dict]

    model_config = ConfigDict(from_attributes=True)


class StepOut(BaseModel):
    key: str
    label: str
    state: str
    detail: Optional[str] = ""
    at: Optional[datetime] = None


class ApplicationOut(BaseModel):
    id: int
    ambassador_id: Optional[int]
    email: str
    college_email: Optional[str]
    phone: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    university: Optional[str]
    sport: Optional[str]
    year: Optional[str]
    campus_channel: Optional[str]
    roster_link: Optional[str]
    international: Optional[bool]
    instagram: Optional[str]
    instagram_followers: Optional[str]
    tiktok: Optional[str]
    tiktok_followers: Optional[str]
    youtube: Optional[str]
    youtube_subscribers: Optional[str]
    other_followers: Optional[str]
    nil_deals_done: Optional[str]
    nil_deals_wanted: Optional[str]
    purpose: Optional[str]
    content_type: Optional[str]
    description: Optional[str]
    confirm_age: bool
    consent_terms: bool
    consent_program_email: bool
    consent_sms: bool
    consent_marketing: bool
    consent_partners: bool
    consent_version: Optional[str]
    consent_at: Optional[datetime]
    source: str
    submit_count: int
    status: str
    decline_reason: Optional[str]
    reviewed_at: Optional[datetime]
    reviewed_by: Optional[str]
    docusign_envelope_id: Optional[str]
    docusign_status: Optional[str]
    agreement_sent_at: Optional[datetime]
    agreement_reminded_at: Optional[datetime] = None
    signed_at: Optional[datetime]
    stripe_account_id: Optional[str]
    stripe_payouts_enabled: Optional[bool]
    stripe_requirements_due: Optional[list[str]]
    stripe_disabled_reason: Optional[str]
    stripe_link_sent_at: Optional[datetime]
    stripe_checked_at: Optional[datetime]
    accepted_at: Optional[datetime]
    notes: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    progress: list[StepOut] = []
    payout_link: Optional[str] = None
    missing_for_approval: list[str] = []   # empty = Approve allowed
    campus_channel_label: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ApplicationDetailOut(ApplicationOut):
    answers: Optional[dict] = None
    events: list[EventOut] = []


def _out(app: Application, detail: bool = False) -> ApplicationOut:
    cls = ApplicationDetailOut if detail else ApplicationOut
    data = cls.model_validate(app)
    data.progress = [StepOut(**s) for s in pipeline.progress(app)]
    data.missing_for_approval = pipeline.missing_for_approval(app)
    data.campus_channel_label = schools.CHANNEL_LABELS.get(app.campus_channel or "", app.campus_channel)
    if app.stripe_account_id:
        try:
            data.payout_link = stripe_connect.payout_link(app.stripe_account_id)
        except stripe_connect.StripeError:
            data.payout_link = None
    return data


@router.get("/", response_model=list[ApplicationOut])
def list_applications(
    status: str = Query("all", description="applicant | approved | declined | agreement_sent | signed | stripe_pending | accepted | open (= not declined/accepted) | all"),
    university: Optional[str] = Query(None),
    sport: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="name / email / handle contains"),
    limit: int = Query(500, le=2000),
    db: Session = Depends(get_db),
):
    query = db.query(Application)
    if status == "open":
        query = query.filter(Application.status.notin_(("declined", "accepted")))
    elif status != "all":
        if status not in pipeline.STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {pipeline.STATUSES + ('open', 'all')}")
        query = query.filter(Application.status == status)
    if university:
        query = query.filter(Application.university.ilike(f"%{university}%"))
    if sport:
        query = query.filter(Application.sport.ilike(f"%{sport}%"))
    if q:
        like = f"%{q.strip().lstrip('@')}%"
        query = query.filter(
            Application.email.ilike(like) | Application.first_name.ilike(like)
            | Application.last_name.ilike(like) | Application.instagram.ilike(like)
        )
    rows = query.order_by(Application.created_at.desc()).limit(limit).all()
    return [_out(a) for a in rows]


@router.get("/summary")
def applications_summary(db: Session = Depends(get_db)):
    rows = db.query(Application.status, Application.university, Application.sport,
                    Application.campus_channel, Application.created_at).all()
    by_status = {s: 0 for s in pipeline.STATUSES}
    by_school: dict[str, int] = {}
    by_sport: dict[str, int] = {}
    by_channel: dict[str, int] = {}
    month_start = datetime.now(tz=timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    applied_this_month = 0
    for status, uni, sport, channel, created in rows:
        by_status[status] = by_status.get(status, 0) + 1
        if uni:
            by_school[uni] = by_school.get(uni, 0) + 1
        if sport:
            by_sport[sport] = by_sport.get(sport, 0) + 1
        if channel:
            by_channel[channel] = by_channel.get(channel, 0) + 1
        if created and created >= month_start:
            applied_this_month += 1
    return {
        "total": len(rows),
        "by_status": by_status,
        "in_progress": sum(v for k, v in by_status.items() if k in ("approved", "agreement_sent", "signed", "stripe_pending")),
        "schools": sorted(by_school),
        "sports": sorted(by_sport),
        "by_school": dict(sorted(by_school.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_sport": dict(sorted(by_sport.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_channel": {k: {"label": schools.CHANNEL_LABELS.get(k, k), "count": v}
                       for k, v in sorted(by_channel.items(), key=lambda kv: (-kv[1], kv[0]))},
        "applied_this_month": applied_this_month,
        "integrations": {
            "docusign": docusign.is_configured(),
            "docusign_powerform": bool(docusign.get_settings().docusign_powerform_url),
            "stripe": stripe_connect.is_configured(),
            "payout_links": bool(docusign.get_settings().link_signing_secret),
            "email": bool(docusign.get_settings().from_email),
        },
    }


def _get(db: Session, application_id: int) -> Application:
    app = db.query(Application).filter(Application.id == application_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@router.get("/{application_id}", response_model=ApplicationDetailOut)
def get_application(application_id: int, db: Session = Depends(get_db)):
    return _out(_get(db, application_id), detail=True)


class ReviewIn(BaseModel):
    by: Optional[str] = None
    reason: Optional[str] = None
    notify: bool = False


@router.post("/{application_id}/approve", response_model=ApplicationDetailOut)
def approve_application(application_id: int, payload: Optional[ReviewIn] = None, db: Session = Depends(get_db)):
    app = _get(db, application_id)
    try:
        result = pipeline.approve(db, app, by=(payload.by if payload and payload.by else "staff"))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    db.refresh(app)
    # If the agreement did not go out, the reason is on the timeline as an
    # 'error' event and the progress step reads "sending"; the row stays
    # approved so staff can hit resend.
    log.info("approve application=%s result=%s", app.id, result)
    return _out(app, detail=True)


@router.post("/{application_id}/decline", response_model=ApplicationDetailOut)
def decline_application(application_id: int, payload: Optional[ReviewIn] = None, db: Session = Depends(get_db)):
    app = _get(db, application_id)
    try:
        pipeline.decline(db, app, reason=(payload.reason if payload else "") or "",
                         by=(payload.by if payload and payload.by else "staff"),
                         notify=bool(payload and payload.notify))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    db.refresh(app)
    return _out(app, detail=True)


@router.post("/{application_id}/resend-agreement")
def resend_agreement(application_id: int, db: Session = Depends(get_db)):
    app = _get(db, application_id)
    try:
        result = pipeline.send_agreement(db, app)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"application": _out(app, detail=True), **result}


@router.post("/{application_id}/resend-stripe-link")
def resend_stripe_link(application_id: int, db: Session = Depends(get_db)):
    app = _get(db, application_id)
    try:
        result = pipeline.start_stripe(db, app)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"application": _out(app, detail=True), **result}


@router.post("/{application_id}/refresh")
def refresh_application(application_id: int, db: Session = Depends(get_db)):
    """Pull live DocuSign + Stripe state for the row (the webhooks normally
    do this; refresh is for 'did it go through?' moments)."""
    app = _get(db, application_id)
    ds = pipeline.refresh_docusign(db, app)
    st = pipeline.refresh_stripe(db, app) if app.stripe_account_id else {"status": app.status}
    db.refresh(app)
    return {"application": _out(app, detail=True), "docusign": ds, "stripe": st}


class ApplicationUpdate(BaseModel):
    notes: Optional[str] = None
    international: Optional[bool] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    university: Optional[str] = None
    sport: Optional[str] = None
    year: Optional[str] = None
    instagram: Optional[str] = None
    roster_link: Optional[str] = None
    tiktok: Optional[str] = None
    youtube: Optional[str] = None
    phone: Optional[str] = None
    ambassador_id: Optional[int] = None


@router.post("/{application_id}/update", response_model=ApplicationDetailOut)
def update_application(application_id: int, payload: ApplicationUpdate, db: Session = Depends(get_db)):
    app = _get(db, application_id)
    fields = payload.model_dump(exclude_unset=True)
    if "instagram" in fields:
        fields["instagram"] = pipeline.normalize_handle(fields["instagram"])
    if "tiktok" in fields:
        fields["tiktok"] = pipeline.normalize_handle(fields["tiktok"])
    if fields.get("university"):
        fields["university"], _ = schools.canonical(fields["university"])   # spelling guard on staff edits too
    for k, v in fields.items():
        setattr(app, k, v)
    app.updated_at = pipeline.now_utc()
    pipeline.record(db, app, "note" if list(fields) == ["notes"] else "edited", actor="staff",
                    detail={k: (v if k != "notes" else "…") for k, v in fields.items()})
    db.commit()
    db.refresh(app)
    return _out(app, detail=True)
