"""Re-check every open application against DocuSign and Stripe.

DocuSign Connect and the Stripe ``account.updated`` webhook normally move a
row forward. If a delivery is missed, the row would sit in its old state
until someone pressed Refresh. A reconcile run does that Refresh for every
open row:

  - approved / agreement_sent with an envelope -> DocuSign envelope status.
    A completed envelope goes through the normal path (signed -> Stripe
    account + payout link email), exactly as the webhook would.
  - signed / stripe_pending with a Stripe account -> Stripe account state.
    Payouts enabled with nothing due -> accepted.

Rows with no change only get ``stripe_checked_at`` bumped, so the timeline
stays readable. Every change is a webhook that never arrived; it lands in the
row's timeline (DocuSign detail ``"event": "reconcile"``, Stripe actor
``reconcile``) and in the run's ``stats.changes``.

Signed rows without a Stripe account (signed by hand before the pipeline
existed) are counted and left alone: starting Stripe for them emails a payout
link, which is a staff decision.

Per-row provider errors become ``error`` events and the run continues.

Callers: the nightly job (``backend.jobs.reconcile_applications``) and the
dashboard's "Refresh all" button (``POST /api/applications/reconcile``).
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.models import Application, ReconcileRun
from backend.onboarding import docusign, pipeline, stripe_connect
from backend.onboarding.pipeline import now_utc, record

logger = logging.getLogger(__name__)

ACTOR = "reconcile"
DOCUSIGN_STATUSES = ("approved", "agreement_sent")
STRIPE_STATUSES = ("signed", "stripe_pending")
# A run that has not finished after this long is treated as dead (process
# restarted mid-run), so it no longer blocks a new one.
STALE_AFTER = timedelta(minutes=15)


def running(db: Session) -> Optional[ReconcileRun]:
    """The run still in progress, if any."""
    return (db.query(ReconcileRun)
            .filter(ReconcileRun.finished_at.is_(None),
                    ReconcileRun.started_at > now_utc() - STALE_AFTER)
            .order_by(ReconcileRun.id.desc()).first())


def start(db: Session, trigger: str, by: Optional[str] = None) -> ReconcileRun:
    run = ReconcileRun(trigger=trigger, triggered_by=by, started_at=now_utc())
    db.add(run)
    db.commit()
    return run


def _name(app: Application) -> str:
    return " ".join(p for p in (app.first_name, app.last_name) if p) or app.email


def _stripe_unchanged(app: Application, state: dict) -> bool:
    due = sorted(set(state["currently_due"]) | set(state["past_due"]))
    return (bool(app.stripe_payouts_enabled) == state["payouts_enabled"]
            and sorted(app.stripe_requirements_due or []) == due
            and (app.stripe_disabled_reason or None) == (state.get("disabled_reason") or None))


def _check_docusign(db: Session, app: Application, stats: Counter, changes: list) -> None:
    try:
        st = docusign.envelope_status(app.docusign_envelope_id)
    except docusign.DocuSignError as e:
        stats["errors"] += 1
        record(db, app, "error", actor=ACTOR, detail={"step": "reconcile_docusign", "error": str(e)})
        db.commit()
        return
    stats["docusign_checked"] += 1
    before = app.docusign_status or ""
    if not st["status"] or st["status"] == before:
        return
    stats["docusign_changed"] += 1
    status_before = app.status
    result = pipeline.on_envelope_event(db, app, {
        "event": "reconcile", "envelope_id": app.docusign_envelope_id,
        "status": st["status"], "completed_at": st.get("completed_at"),
    })
    if st["status"] == "completed":
        stats["signed"] += 1
    if result.get("error"):
        stats["errors"] += 1
    changes.append({"id": app.id, "name": _name(app), "source": "docusign",
                     "from": f"{status_before} / {before or '-'}", "to": f"{app.status} / {st['status']}"})


def _check_stripe(db: Session, app: Application, stats: Counter, changes: list) -> None:
    try:
        acct = stripe_connect.get_account(app.stripe_account_id)
    except stripe_connect.StripeError as e:
        stats["errors"] += 1
        record(db, app, "error", actor=ACTOR, detail={"step": "reconcile_stripe", "error": str(e)})
        db.commit()
        return
    stats["stripe_checked"] += 1
    state = stripe_connect.account_state(acct)
    if _stripe_unchanged(app, state):
        app.stripe_checked_at = now_utc()
        db.commit()
        return
    stats["stripe_changed"] += 1
    status_before = app.status
    pipeline.on_stripe_account(db, app, acct, actor=ACTOR)
    if app.status == "accepted":
        stats["accepted"] += 1
    due = len(set(state["currently_due"]) | set(state["past_due"]))
    changes.append({"id": app.id, "name": _name(app), "source": "stripe",
                    "from": status_before,
                    "to": f"{app.status} / payouts {'on' if state['payouts_enabled'] else 'off'}, {due} due"})


def execute(db: Session, run: ReconcileRun) -> ReconcileRun:
    """Check every open row and finish ``run`` with its stats."""
    ds_on, st_on = docusign.is_configured(), stripe_connect.is_configured()
    stats: Counter = Counter()
    changes: list[dict] = []
    try:
        rows = (db.query(Application)
                .filter(Application.status.in_(DOCUSIGN_STATUSES + STRIPE_STATUSES))
                .order_by(Application.id).all())
        stats["rows"] = len(rows)
        for app in rows:
            status = app.status  # the DocuSign step can move a row on; check each row once
            if status in DOCUSIGN_STATUSES and app.docusign_envelope_id and ds_on:
                _check_docusign(db, app, stats, changes)
            elif status in STRIPE_STATUSES and app.stripe_account_id and st_on:
                _check_stripe(db, app, stats, changes)
            elif status == "signed" and not app.stripe_account_id:
                stats["signed_no_stripe"] += 1
    except Exception as e:  # keep the partial stats; the caller decides how loud to be
        db.rollback()
        run.error = f"{type(e).__name__}: {e}"
        logger.exception("reconcile run %s crashed", run.id)
    run.stats = {**stats, "changed": stats["docusign_changed"] + stats["stripe_changed"],
                 "docusign_configured": ds_on, "stripe_configured": st_on, "changes": changes}
    if stats["errors"] and not run.error:
        run.error = f"{stats['errors']} row(s) errored; see application_events kind=error"
    run.finished_at = now_utc()
    db.commit()
    logger.info(
        "reconcile run %s (%s): %d rows | DocuSign checked %d, changed %d (signed %d) | "
        "Stripe checked %d, changed %d (accepted %d) | signed without Stripe %d | errors %d",
        run.id, run.trigger, stats["rows"], stats["docusign_checked"], stats["docusign_changed"],
        stats["signed"], stats["stripe_checked"], stats["stripe_changed"], stats["accepted"],
        stats["signed_no_stripe"], stats["errors"],
    )
    return run
