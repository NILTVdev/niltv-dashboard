"""Onboarding reconcile: the nightly job / "Refresh all" catches what a
missed webhook left behind. DocuSign, Stripe and SES are stubbed."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.database import SessionLocal
from backend.main import app
from backend.models import Application, ApplicationEvent, ReconcileRun
from backend.onboarding import docusign, mailer, reconcile, stripe_connect
from backend.onboarding.pipeline import now_utc
from backend.jobs import reconcile_applications as job

client = TestClient(app)
AUTH = {"X-API-Key": "test"}

DUE = ["external_account", "tos_acceptance.date"]


def _clean(db):
    db.query(ApplicationEvent).delete()
    db.query(Application).delete()
    db.query(ReconcileRun).delete()
    db.commit()


@pytest.fixture()
def db():
    session = SessionLocal()
    _clean(session)
    yield session
    _clean(session)
    session.close()


@pytest.fixture()
def fakes(monkeypatch):
    """envelopes: envelope id -> DocuSign status; accounts: acct id -> account object."""
    state = {"envelopes": {}, "accounts": {}, "mail": [], "created": []}
    monkeypatch.setattr(docusign, "is_configured", lambda: True)
    monkeypatch.setattr(stripe_connect, "is_configured", lambda: True)

    def _status(env_id):
        st = state["envelopes"][env_id]
        if st == "boom":
            raise docusign.DocuSignError("DocuSign 500")
        return {"status": st, "completed_at": "2026-10-10T12:00:00Z"}
    monkeypatch.setattr(docusign, "envelope_status", _status)
    monkeypatch.setattr(stripe_connect, "get_account", lambda acct: state["accounts"][acct])

    def _create(email, metadata, name=""):
        state["created"].append(email)
        return {"id": "acct_NEW", "payouts_enabled": False, "requirements": {"currently_due": DUE}}
    monkeypatch.setattr(stripe_connect, "create_express_account", _create)
    monkeypatch.setattr(stripe_connect, "payout_link", lambda acct: f"https://niltv.com/payouts/start/?t={acct}")
    monkeypatch.setattr(mailer, "send_stripe_link", lambda to, name, link: state["mail"].append(to) or True)
    return state


def _row(db, email, status, **kw):
    a = Application(email=email, first_name=email.split("@")[0].title(), status=status, **kw)
    db.add(a)
    db.commit()
    return a


def _acct(payouts, due):
    return {"payouts_enabled": payouts, "requirements": {"currently_due": due, "past_due": due}}


def test_catches_missed_webhooks_and_leaves_the_rest(db, fakes):
    unopened = _row(db, "a@x.com", "agreement_sent", docusign_envelope_id="e1", docusign_status="sent")
    signed_late = _row(db, "b@x.com", "agreement_sent", docusign_envelope_id="e2", docusign_status="delivered")
    finished = _row(db, "c@x.com", "stripe_pending", stripe_account_id="acct_C",
                    stripe_payouts_enabled=False, stripe_requirements_due=DUE)
    idle = _row(db, "d@x.com", "stripe_pending", stripe_account_id="acct_D",
                stripe_payouts_enabled=False, stripe_requirements_due=DUE)
    hand_signed = _row(db, "e@x.com", "signed")
    fakes["envelopes"].update({"e1": "sent", "e2": "completed"})
    fakes["accounts"].update({"acct_C": _acct(True, []), "acct_D": _acct(False, DUE)})

    run = reconcile.execute(db, reconcile.start(db, "nightly"))

    for a in (unopened, signed_late, finished, idle, hand_signed):
        db.refresh(a)
    assert unopened.status == "agreement_sent"
    assert signed_late.status == "stripe_pending" and signed_late.stripe_account_id == "acct_NEW"
    assert fakes["mail"] == ["b@x.com"]          # payout link only for the newly signed row
    assert finished.status == "accepted"
    assert idle.status == "stripe_pending" and idle.stripe_checked_at is not None
    assert hand_signed.status == "signed" and fakes["created"] == ["b@x.com"]

    s = run.stats
    assert run.finished_at and not run.error
    assert (s["docusign_checked"], s["stripe_checked"], s["changed"]) == (2, 2, 2)
    assert (s["signed"], s["accepted"], s["signed_no_stripe"]) == (1, 1, 1)
    assert {c["id"] for c in s["changes"]} == {signed_late.id, finished.id}

    # Unchanged rows add nothing to the timeline.
    kinds = {e.kind for e in db.query(ApplicationEvent).filter_by(application_id=idle.id)}
    assert kinds == set()


def test_provider_error_is_logged_and_run_continues(db, fakes):
    bad = _row(db, "a@x.com", "agreement_sent", docusign_envelope_id="e1", docusign_status="sent")
    ok = _row(db, "b@x.com", "stripe_pending", stripe_account_id="acct_B",
              stripe_payouts_enabled=False, stripe_requirements_due=DUE)
    fakes["envelopes"]["e1"] = "boom"
    fakes["accounts"]["acct_B"] = _acct(True, [])

    with pytest.raises(RuntimeError):
        job.reconcile_applications(db)  # nightly job fails loudly -> SNS alert

    db.refresh(ok)
    assert ok.status == "accepted"
    err = db.query(ApplicationEvent).filter_by(application_id=bad.id, kind="error").one()
    assert err.detail["step"] == "reconcile_docusign"
    run = db.query(ReconcileRun).one()
    assert run.stats["errors"] == 1 and run.error


def test_refresh_all_endpoint_and_run_log(db, fakes):
    _row(db, "c@x.com", "stripe_pending", stripe_account_id="acct_C",
         stripe_payouts_enabled=False, stripe_requirements_due=DUE)
    fakes["accounts"]["acct_C"] = _acct(True, [])

    assert client.post("/api/applications/reconcile").status_code in (401, 403)
    r = client.post("/api/applications/reconcile", headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["trigger"] == "staff"

    runs = client.get("/api/applications/reconcile/runs", headers=AUTH).json()
    assert runs[0]["finished_at"] and runs[0]["stats"]["accepted"] == 1
    assert runs[0]["stats"]["changes"][0]["source"] == "stripe"


def test_one_run_at_a_time(db, fakes):
    active = reconcile.start(db, "staff")
    r = client.post("/api/applications/reconcile", headers=AUTH)
    assert r.status_code == 409
    assert job.reconcile_applications(db) == 0   # nightly skips while a staff run is live

    active.started_at = now_utc() - timedelta(minutes=20)  # died mid-run
    db.commit()
    assert reconcile.running(db) is None


def test_scope_limits_the_run(db, fakes):
    waiting = _row(db, "a@x.com", "agreement_sent", docusign_envelope_id="e1", docusign_status="sent")
    done = _row(db, "b@x.com", "accepted", stripe_account_id="acct_B",
                stripe_payouts_enabled=True, stripe_requirements_due=[])
    fakes["envelopes"]["e1"] = "completed"
    fakes["accounts"]["acct_B"] = _acct(False, ["external_account"])  # bank removed

    r = client.post("/api/applications/reconcile?scope=accepted", headers=AUTH)
    assert r.status_code == 200, r.text
    db.refresh(waiting)
    db.refresh(done)
    assert waiting.status == "agreement_sent"          # out of scope, untouched
    assert done.status == "accepted" and done.stripe_requirements_due == ["external_account"]
    run = client.get("/api/applications/reconcile/runs", headers=AUTH).json()[0]
    assert run["stats"]["scope"] == "accepted" and run["stats"].get("accepted", 0) == 0
    assert run["stats"]["changed"] == 1

    assert client.post("/api/applications/reconcile?scope=declined", headers=AUTH).status_code == 400
