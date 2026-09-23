"""Onboarding state machine for athlete applications.

    applicant -> approved -> agreement_sent -> signed -> stripe_pending -> accepted
              \\-> declined

Every transition writes an ``application_events`` row so the dashboard can
show what an athlete still needs and staff can audit who did what. External
calls (DocuSign, Stripe, SES) live in sibling modules; failures there are
recorded as ``error`` events and surfaced in the API response rather than
raised, so a flaky provider never loses the staff action.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models import Ambassador, Application, ApplicationEvent
from backend.onboarding import docusign, mailer, schools, stripe_connect

log = logging.getLogger(__name__)

STATUSES = ("applicant", "approved", "declined", "agreement_sent", "signed", "stripe_pending", "accepted")
PROGRAM = "ambassador-fall-2026"

# Form field (camelCase, from niltv.com/athlete-signup/) -> column.
FIELD_MAP = {
    "email": "email",
    "collegeEmail": "college_email",
    "phone": "phone",
    "firstName": "first_name",
    "lastName": "last_name",
    "university": "university",
    "sport": "sport",
    "year": "year",
    "campusChannel": "campus_channel",
    "rosterLink": "roster_link",
    "instagram": "instagram",
    "instagramFollowers": "instagram_followers",
    "tiktok": "tiktok",
    "tiktokFollowers": "tiktok_followers",
    "youtube": "youtube",
    "youtubeSubscribers": "youtube_subscribers",
    "otherFollowers": "other_followers",
    "nilDealsDone": "nil_deals_done",
    "nilDealsWanted": "nil_deals_wanted",
    "purpose": "purpose",
    "contentType": "content_type",
    "description": "description",
}
CONSENT_FIELDS = {
    "confirmAge": "confirm_age",
    "consentTerms": "consent_terms",
    "consentProgramEmail": "consent_program_email",
    "consentSms": "consent_sms",
    "consentMarketing": "consent_marketing",
    "consentPartners": "consent_partners",
}
HANDLE_FIELDS = ("instagram", "tiktok")
_YES = {"yes", "y", "true", "1", "on", "international"}


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_handle(value: Any) -> Optional[str]:
    """'@Jane.Doe' or 'https://instagram.com/jane.doe/' -> 'jane.doe'"""
    if not value:
        return None
    v = str(value).strip()
    v = re.sub(r"^https?://(www\.)?(instagram\.com|tiktok\.com)/", "", v, flags=re.I)
    v = v.split("?")[0].strip("/").lstrip("@").strip().lower()
    return v or None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in _YES


def _international(value: Any) -> Optional[bool]:
    if value is None or value == "":
        return None
    v = str(value).strip().lower()
    if v in _YES:
        return True
    if v.startswith("no") or v in {"false", "0", "domestic", "us", "u.s."}:
        return False
    return None


def record(db: Session, app: Application, kind: str, actor: str = "system",
           detail: Optional[dict] = None, at: Optional[datetime] = None) -> ApplicationEvent:
    ev = ApplicationEvent(application_id=app.id, kind=kind, actor=actor,
                          detail=detail or {}, at=at or now_utc())
    db.add(ev)
    return ev


# -- Intake -----------------------------------------------------------------

def normalize_name(value: str) -> str:
    """Trim, and capitalise a name typed entirely in lower case ("jordan" ->
    "Jordan"). Mixed-case input (McKenna, DeShawn) is kept as typed; it feeds
    the DocuSign greeting and the Stripe display name."""
    value = str(value).strip()
    if value and value == value.lower():
        return value[:1].upper() + value[1:]
    return value


def intake(db: Session, payload: dict, *, ip: Optional[str] = None,
           source: Optional[str] = None, applied_at: Optional[datetime] = None,
           notify: bool = True) -> tuple[Application, bool]:
    """Upsert an application from a form payload. Returns (row, created).

    Re-submitting with the same email updates the answers, bumps
    submit_count, and never resets the onboarding status. A declined
    applicant re-applying stays declined (staff can re-approve).

    ``applied_at`` backdates a new row (Google Form backfill); ``notify``
    controls the staff email on create. consent_at is stamped only when the
    payload carries consent fields (the legacy Google Form has none).
    """
    email = normalize_email(payload.get("email") or payload.get("collegeEmail"))
    if not email or "@" not in email:
        raise ValueError("email is required")

    app = db.query(Application).filter(Application.email == email).first()
    created = app is None
    if created:
        app = Application(email=email, status="applicant")
        db.add(app)
        db.flush()

    for key, col in FIELD_MAP.items():
        if key in payload and payload[key] not in (None, ""):
            value = payload[key]
            if key in HANDLE_FIELDS:
                value = normalize_handle(value)
            elif key == "youtube":
                value = str(value).strip()
            elif key in ("email", "collegeEmail"):
                value = normalize_email(value)
            elif key in ("firstName", "lastName"):
                value = normalize_name(value)
            setattr(app, col, value)
    for key, col in CONSENT_FIELDS.items():
        if key in payload:
            setattr(app, col, _as_bool(payload[key]))
    if "international" in payload:
        app.international = _international(payload["international"])

    # Spelling guard: the school is stored under its official IPEDS name; what
    # the athlete typed is kept in answers. The campus channel is stored as a
    # slug and inferred from the school when the form left it blank.
    if payload.get("university"):
        official, matched = schools.canonical(payload["university"])
        app.university = official
        payload["universityAsTyped"] = payload["university"]
        payload["universityMatched"] = bool(matched or payload.get("universityMatched"))
    if payload.get("campusChannel") or app.university:
        slug = schools.channel_slug(payload.get("campusChannel"), app.university)
        if slug:
            app.campus_channel = slug

    app.email = email
    app.answers = {k: v for k, v in payload.items() if k not in ("userAgent",)}
    if payload.get("account"):
        app.answers["account"] = payload["account"]   # {sub, emailVerified, pool} from the site login
    app.consent_version = payload.get("consentVersion") or app.consent_version
    if any(k in payload for k in CONSENT_FIELDS):
        app.consent_at = applied_at or now_utc()
    app.source = source or payload.get("source") or app.source or "athlete-signup"
    app.user_agent = (payload.get("userAgent") or "")[:400] or app.user_agent
    if ip:
        app.ip = ip
    if not created:
        app.submit_count = (app.submit_count or 1) + 1
    elif applied_at:
        app.created_at = applied_at
    app.updated_at = now_utc()

    # Link (never merge) with the tracking registry by IG handle.
    if app.instagram and not app.ambassador_id:
        amb = db.query(Ambassador).filter(Ambassador.ig_username == app.instagram).first()
        if amb:
            app.ambassador_id = amb.id

    record(db, app, "applied" if created else "resubmitted", actor="athlete",
           detail={"source": app.source, "submit_count": app.submit_count,
                   **({"tab": payload["formTab"]} if payload.get("formTab") else {})},
           at=applied_at)
    db.commit()
    db.refresh(app)

    if created and notify:
        mailer.send_application_received(app.email, app.first_name or "")
        summary = (
            f"{app.first_name or ''} {app.last_name or ''}\n{app.email}\n"
            f"{app.university or '?'} / {app.sport or '?'} / {app.year or '?'}\n"
            f"IG @{app.instagram or '?'} ({app.instagram_followers or '?'} followers)\n"
            f"International: {app.international}"
        )
        mailer.notify_staff_new_applicant(summary, f"{_dashboard_base()}/niltv-onboarding?id={app.id}")
    return app, created


def _dashboard_base() -> str:
    return get_settings().dashboard_base_url.rstrip("/")


# -- Review -----------------------------------------------------------------

APPROVAL_FIELDS = ("name", "email", "roster link", "a social link")


def missing_for_approval(app: Application) -> list[str]:
    """What staff need before Approve is allowed: name, email, roster link,
    and at least one social link."""
    missing = []
    if not (app.first_name and app.last_name):
        missing.append("name")
    if not app.email:
        missing.append("email")
    if not app.roster_link:
        missing.append("roster link")
    if not (app.instagram or app.tiktok or app.youtube):
        missing.append("a social link")
    return missing


def approve(db: Session, app: Application, by: str = "staff") -> dict:
    """approved -> immediately try to send the agreement. Returns a result
    dict with 'sent' and 'error' so the UI can say what happened."""
    if app.status not in ("applicant", "declined", "approved"):
        raise ValueError(f"cannot approve from status {app.status}")
    missing = missing_for_approval(app)
    if missing and app.status != "approved":
        raise ValueError("cannot approve: missing " + ", ".join(missing))
    now = now_utc()
    app.status = "approved"
    app.reviewed_at = now
    app.reviewed_by = by
    app.decline_reason = None
    app.updated_at = now
    record(db, app, "approved", actor="staff", detail={"by": by})
    db.commit()
    return send_agreement(db, app)


def decline(db: Session, app: Application, reason: str = "", by: str = "staff",
            notify: bool = False) -> None:
    if app.status in ("signed", "stripe_pending", "accepted"):
        raise ValueError(f"cannot decline from status {app.status}; use notes and deactivate instead")
    now = now_utc()
    app.status = "declined"
    app.reviewed_at = now
    app.reviewed_by = by
    app.decline_reason = reason or None
    app.updated_at = now
    record(db, app, "declined", actor="staff", detail={"by": by, "reason": reason, "notified": notify})
    # An agreement still out for signature is withdrawn so the applicant
    # cannot sign after the decision.
    if app.docusign_envelope_id and app.docusign_status not in ("completed", "voided", "declined")             and docusign.is_configured():
        try:
            docusign.void_envelope(app.docusign_envelope_id, "Application declined")
            app.docusign_status = "voided"
            record(db, app, "envelope_voided", actor="system", detail={"envelope_id": app.docusign_envelope_id})
        except docusign.DocuSignError as e:
            record(db, app, "error", actor="system", detail={"step": "void_envelope", "error": str(e)})
    db.commit()
    if notify:
        mailer.send_declined(app.email, app.first_name or "")


def send_agreement(db: Session, app: Application) -> dict:
    """Create the DocuSign envelope (or email the PowerForm fallback).
    approved -> agreement_sent. Idempotent: an existing envelope is re-sent,
    which keeps agreement_sent_at (when it first went out) and stamps
    agreement_reminded_at instead."""
    if app.status not in ("approved", "agreement_sent"):
        raise ValueError(f"cannot send agreement from status {app.status}")
    s = get_settings()
    name = f"{app.first_name or ''} {app.last_name or ''}".strip() or app.email
    result: dict = {"sent": False, "mode": None, "error": None}
    try:
        if app.docusign_envelope_id and docusign.is_configured():
            docusign.resend(app.docusign_envelope_id)
            result.update(sent=True, mode="docusign-resend")
            # DocuSign resets the recipient to "sent" until the new email is opened.
            app.docusign_status = "sent"
            app.agreement_reminded_at = now_utc()
            record(db, app, "agreement_resent", actor="staff",
                   detail={"envelope_id": app.docusign_envelope_id})
        elif docusign.is_configured():
            env_id = docusign.create_envelope(docusign.EnvelopeFields(
                email=app.email, name=name, school=app.university or "",
                sport=app.sport or "", handle=app.instagram or "", application_id=app.id,
            ))
            app.docusign_envelope_id = env_id
            app.docusign_status = "sent"
            result.update(sent=True, mode="docusign")
            record(db, app, "agreement_sent", actor="system", detail={"envelope_id": env_id, "mode": "docusign"})
        elif s.docusign_powerform_url:
            ok = mailer.send_powerform_agreement(app.email, app.first_name or "", s.docusign_powerform_url)
            result.update(sent=ok, mode="powerform")
            record(db, app, "agreement_sent" if ok else "error", actor="system",
                   detail={"mode": "powerform", "email_sent": ok})
            if not ok:
                result["error"] = "PowerForm email could not be sent"
        else:
            result["error"] = "DocuSign is not configured (no API credentials and no PowerForm URL)"
            record(db, app, "error", actor="system", detail={"step": "send_agreement", "error": result["error"]})
    except docusign.DocuSignError as e:
        result["error"] = str(e)
        record(db, app, "error", actor="system", detail={"step": "send_agreement", "error": str(e)})

    if result["sent"]:
        app.status = "agreement_sent"
        if result["mode"] != "docusign-resend" or app.agreement_sent_at is None:
            app.agreement_sent_at = now_utc()
    app.updated_at = now_utc()
    db.commit()
    return result


# -- DocuSign -> Stripe -----------------------------------------------------

def find_by_envelope(db: Session, envelope_id: Optional[str], signer_email: Optional[str],
                     custom_fields: Optional[dict] = None) -> Optional[Application]:
    app = None
    if envelope_id:
        app = db.query(Application).filter(Application.docusign_envelope_id == envelope_id).first()
    if app is None and custom_fields and custom_fields.get("application_id", "").isdigit():
        app = db.query(Application).filter(Application.id == int(custom_fields["application_id"])).first()
    if app is None and signer_email:
        # PowerForm path: the envelope was never created by us, match on email.
        app = db.query(Application).filter(Application.email == normalize_email(signer_email)).first()
    return app


def on_envelope_event(db: Session, app: Application, event: dict) -> dict:
    """Apply a DocuSign Connect event. Completed -> signed -> Stripe."""
    status = (event.get("status") or "").lower()
    env_id = event.get("envelope_id")
    if env_id and not app.docusign_envelope_id:
        app.docusign_envelope_id = env_id
    app.docusign_status = status or app.docusign_status
    record(db, app, f"envelope_{status or 'event'}", actor="docusign",
           detail={"envelope_id": env_id, "event": event.get("event")})
    app.updated_at = now_utc()
    db.commit()

    if status != "completed":
        return {"status": app.status, "docusign_status": app.docusign_status}
    if app.status in ("signed", "stripe_pending", "accepted"):
        return {"status": app.status, "note": "already signed"}  # duplicate delivery

    completed_at = _parse_iso(event.get("completed_at")) or now_utc()
    app.status = "signed"
    app.signed_at = completed_at
    app.updated_at = now_utc()
    record(db, app, "signed", actor="docusign", detail={"envelope_id": env_id}, at=completed_at)
    db.commit()
    return start_stripe(db, app)


def start_stripe(db: Session, app: Application) -> dict:
    """signed -> stripe_pending: create the Express account and email the
    permanent payout link. International athletes skip Stripe and go straight
    to accepted (participate, don't pay)."""
    if app.status not in ("signed", "stripe_pending"):
        raise ValueError(f"cannot start Stripe from status {app.status}")
    if app.international:
        return _accept(db, app, reason="international student")

    result: dict = {"status": app.status, "account_id": app.stripe_account_id, "link_sent": False, "error": None}
    try:
        if not app.stripe_account_id:
            acct = stripe_connect.create_express_account(app.email, {
                "contract_signed": (app.signed_at or now_utc()).date().isoformat(),
                "envelope_id": app.docusign_envelope_id or "",
                "program": PROGRAM,
                "school": app.university or "",
                "sport": app.sport or "",
                "handle": app.instagram or "",
                "application_id": str(app.id),
            }, name=" ".join(p for p in (app.first_name, app.last_name) if p))
            app.stripe_account_id = acct["id"]
            _apply_account_state(app, stripe_connect.account_state(acct))
            record(db, app, "stripe_account_created", actor="system", detail={"account_id": acct["id"]})
            result["account_id"] = acct["id"]
        link = stripe_connect.payout_link(app.stripe_account_id)
        ok = mailer.send_stripe_link(app.email, app.first_name or "", link)
        result["link_sent"] = ok
        record(db, app, "stripe_link_sent" if ok else "error", actor="system",
               detail={"account_id": app.stripe_account_id, "email_sent": ok,
                       **({} if ok else {"step": "send_stripe_link", "error": "email not sent"})})
        if ok:
            app.stripe_link_sent_at = now_utc()
        app.status = "stripe_pending"
        result["status"] = app.status
    except stripe_connect.StripeError as e:
        result["error"] = str(e)
        record(db, app, "error", actor="system", detail={"step": "start_stripe", "error": str(e)})
    app.updated_at = now_utc()
    db.commit()
    return result


def _apply_account_state(app: Application, state: dict) -> None:
    app.stripe_payouts_enabled = state["payouts_enabled"]
    app.stripe_requirements_due = sorted(set(state["currently_due"]) | set(state["past_due"]))
    app.stripe_disabled_reason = state.get("disabled_reason")
    app.stripe_checked_at = now_utc()


def on_stripe_account(db: Session, app: Application, account: dict, actor: str = "stripe") -> dict:
    """Apply an account object (webhook or manual refresh). Complete -> accepted."""
    state = stripe_connect.account_state(account)
    _apply_account_state(app, state)
    record(db, app, "stripe_updated", actor=actor,
           detail={"payouts_enabled": state["payouts_enabled"], "currently_due": state["currently_due"],
                   "past_due": state["past_due"], "disabled_reason": state.get("disabled_reason")})
    app.updated_at = now_utc()
    db.commit()
    if state["complete"] and app.status in ("signed", "stripe_pending"):
        return _accept(db, app, reason="stripe payouts enabled")
    if not state["complete"] and app.status == "accepted":
        # Stripe re-opened requirements (expired ID, bank change). Keep the
        # accepted status, the row shows the due list so staff can chase it.
        record(db, app, "stripe_requirements_reopened", actor=actor, detail={"currently_due": state["currently_due"]})
        db.commit()
    return {"status": app.status, "stripe": state}


def refresh_stripe(db: Session, app: Application) -> dict:
    if not app.stripe_account_id:
        return {"status": app.status, "error": "no Stripe account yet"}
    try:
        acct = stripe_connect.get_account(app.stripe_account_id)
    except stripe_connect.StripeError as e:
        record(db, app, "error", actor="staff", detail={"step": "refresh_stripe", "error": str(e)})
        db.commit()
        return {"status": app.status, "error": str(e)}
    return on_stripe_account(db, app, acct, actor="staff")


def refresh_docusign(db: Session, app: Application) -> dict:
    if not app.docusign_envelope_id or not docusign.is_configured():
        return {"status": app.status, "docusign_status": app.docusign_status}
    try:
        st = docusign.envelope_status(app.docusign_envelope_id)
    except docusign.DocuSignError as e:
        record(db, app, "error", actor="staff", detail={"step": "refresh_docusign", "error": str(e)})
        db.commit()
        return {"status": app.status, "error": str(e)}
    return on_envelope_event(db, app, {
        "event": "manual-refresh", "envelope_id": app.docusign_envelope_id,
        "status": st["status"], "completed_at": st.get("completed_at"),
    })


def _accept(db: Session, app: Application, reason: str) -> dict:
    now = now_utc()
    app.status = "accepted"
    app.accepted_at = now
    app.updated_at = now
    record(db, app, "accepted", actor="system", detail={"reason": reason})
    # Promote the linked registry row so tracking picks them up.
    if app.ambassador_id:
        amb = db.query(Ambassador).filter(Ambassador.id == app.ambassador_id).first()
        if amb and amb.status == "candidate":
            amb.status = "confirmed"
            amb.updated_at = now
    db.commit()
    return {"status": "accepted", "reason": reason}


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        v = value.replace("Z", "+00:00")
        # DocuSign gives 7 fractional digits; Python takes 6.
        v = re.sub(r"(\.\d{6})\d+", r"\1", v)
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# -- Progress view ----------------------------------------------------------

def progress(app: Application) -> list[dict]:
    """The six-step checklist the dashboard renders per row:
    each step = {key, label, state: done|current|todo|skipped|blocked, detail, at}."""
    order = STATUSES
    idx = order.index(app.status) if app.status in order else 0

    def st(step_status_min: str, done_when: bool) -> str:
        if done_when:
            return "done"
        return "current" if order.index(step_status_min) <= idx + 1 else "todo"

    steps = [
        {"key": "applied", "label": "Applied", "state": "done",
         "detail": app.source, "at": app.created_at},
        {"key": "reviewed", "label": "Approved",
         "state": "blocked" if app.status == "declined" else ("done" if idx >= 1 else "current"),
         "detail": (f"Declined: {app.decline_reason or ''}".strip() if app.status == "declined"
                    else (app.reviewed_by or "")),
         "at": app.reviewed_at},
        {"key": "agreement", "label": "Agreement signed",
         "state": ("done" if app.status in ("signed", "stripe_pending", "accepted")
                   else "current" if app.status in ("approved", "agreement_sent") else "todo"),
         "detail": ((f"DocuSign {app.docusign_status}" if app.docusign_status else
                     ("not sent yet" if app.status == "approved" else ""))
                    + (f", reminded {app.agreement_reminded_at:%b} {app.agreement_reminded_at.day}"
                       if app.agreement_reminded_at and app.status in ("approved", "agreement_sent") else "")),
         "at": app.signed_at or app.agreement_sent_at},
    ]
    if app.international:
        steps.append({"key": "stripe", "label": "Stripe payouts", "state": "skipped",
                      "detail": "International student", "at": None})
    else:
        due = list(app.stripe_requirements_due or [])
        if app.status == "accepted" and app.stripe_payouts_enabled and not due:
            s_state, s_detail = "done", "Payouts enabled"
        elif app.stripe_account_id:
            s_state = "current"
            needs = ", ".join(dict.fromkeys(_humanize(d) for d in due))  # deduped, order kept
            s_detail = ("Payouts enabled" if app.stripe_payouts_enabled else
                        (f"Needs: {needs}" if due else
                         ("Link sent, not started" if app.stripe_link_sent_at else "Account created")))
            if app.stripe_disabled_reason:
                s_detail += f" ({app.stripe_disabled_reason})"
        else:
            s_state, s_detail = ("current" if app.status == "signed" else "todo"), ""
        steps.append({"key": "stripe", "label": "Stripe payouts", "state": s_state,
                      "detail": s_detail, "at": app.stripe_checked_at})
    steps.append({"key": "accepted", "label": "Accepted",
                  "state": "done" if app.status == "accepted" else "todo",
                  "detail": "", "at": app.accepted_at})
    return steps


def _humanize(req: str) -> str:
    """'individual.verification.document' -> 'ID document'; keeps unknowns readable."""
    table = {
        "external_account": "bank account",
        "individual.verification.document": "ID document",
        "individual.verification.additional_document": "proof of address",
        "individual.id_number": "SSN",
        "individual.ssn_last_4": "SSN last 4",
        "individual.dob.day": "date of birth",
        "individual.address.line1": "address",
        "individual.phone": "phone",
        "individual.email": "email",
        "individual.first_name": "legal name",
        "individual.last_name": "legal name",
        "tos_acceptance.date": "Stripe terms",
        "business_profile.url": "profile URL",
        "business_profile.mcc": "business category",
    }
    if req in table:
        return table[req]
    for prefix, label in (("individual.dob", "date of birth"), ("individual.address", "address"),
                          ("individual.verification", "ID verification"), ("tos_acceptance", "Stripe terms")):
        if req.startswith(prefix):
            return label
    return req.replace("_", " ").replace(".", " ")
