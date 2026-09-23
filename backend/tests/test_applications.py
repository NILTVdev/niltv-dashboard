"""Functional tests for the athlete onboarding pipeline (migration 025).

Runs in CI against the seeded Postgres. DocuSign / Stripe / SES are never
called: the client modules are monkeypatched at the pipeline seam so the
state machine is exercised end to end:

  form POST -> applicant -> approve (envelope created) -> agreement_sent
  -> Connect webhook completed -> signed -> Stripe account + link -> stripe_pending
  -> account.updated payouts_enabled -> accepted

Plus: upsert on re-submit, honeypot, rate limit, auth, decline, the
international skip, webhook signature verification, and the progress view.
"""

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.database import SessionLocal
from backend.main import app
from backend.models import Ambassador, Application, ApplicationEvent
from backend.onboarding import docusign, mailer, pipeline, stripe_connect
from backend.routers import applications as apps_router

client = TestClient(app)
AUTH = {"X-API-Key": "test"}  # matches DASHBOARD_PASSWORD in the CI env

FORM = {
    "email": "Jane.Doe@Example.com",
    "collegeEmail": "jdoe@duke.edu",
    "phone": "919-555-0100",
    "firstName": "Jane",
    "lastName": "Doe",
    "university": "Duke University",
    "sport": "Lacrosse",
    "year": "Junior",
    "campusChannel": "TrueBlueTV",
    "rosterLink": "https://goduke.com/sports/womens-lacrosse/roster/jane-doe",
    "instagram": "@Jane.Doe",
    "instagramFollowers": "12,400",
    "tiktok": "https://www.tiktok.com/@janedoe",
    "international": "No",
    "nilDealsDone": "Yes",
    "purpose": "Grow my brand",
    "confirmAge": True,
    "consentTerms": True,
    "consentProgramEmail": True,
    "consentSms": False,
    "consentMarketing": True,
    "consentPartners": False,
    "source": "athlete-signup",
    "consentVersion": "2026-09-08",
    "submittedAt": "2026-09-09T12:00:00Z",
    "userAgent": "pytest",
}


def _clean(db):
    db.query(ApplicationEvent).delete()
    db.query(Application).delete()
    db.query(Ambassador).filter(Ambassador.ig_username == "jane.doe").delete()
    db.commit()


@pytest.fixture()
def db():
    session = SessionLocal()
    _clean(session)
    apps_router._hits.clear()
    yield session
    _clean(session)
    session.close()


@pytest.fixture()
def fakes(monkeypatch):
    """Stub every external call and record what was asked."""
    calls = {"envelopes": [], "resent": [], "accounts": [], "mail": [], "declined": []}

    monkeypatch.setattr(docusign, "is_configured", lambda: True)
    monkeypatch.setattr(docusign, "create_envelope", lambda f: calls["envelopes"].append(f) or "env-123")
    monkeypatch.setattr(docusign, "resend", lambda env_id: calls["resent"].append(env_id))

    def _create(email, metadata, name=""):
        calls["accounts"].append((email, metadata))
        return {"id": "acct_TEST1", "payouts_enabled": False,
                "requirements": {"currently_due": ["external_account", "individual.dob.day"]}}
    monkeypatch.setattr(stripe_connect, "create_express_account", _create)
    monkeypatch.setattr(stripe_connect, "payout_link", lambda acct: f"https://niltv.com/payouts/start/?t=TOKEN-{acct}")
    monkeypatch.setattr(mailer, "send_stripe_link", lambda to, name, link: calls["mail"].append((to, link)) or True)
    monkeypatch.setattr(mailer, "send_declined", lambda to, name: calls["declined"].append(to) or True)
    monkeypatch.setattr(mailer, "notify_staff_new_applicant", lambda *a, **k: True)
    monkeypatch.setattr(mailer, "send_application_received", lambda *a, **k: True)
    return calls


# -- Intake -----------------------------------------------------------------

def test_public_post_creates_applicant(db, fakes):
    r = client.post("/api/applications/", json=FORM)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["created"] is True

    app = db.query(Application).filter(Application.email == "jane.doe@example.com").one()
    assert app.status == "applicant"
    assert app.first_name == "Jane" and app.university == "Duke University"
    assert app.instagram == "jane.doe"          # normalized: lowercased, no @
    assert app.tiktok == "janedoe"              # URL stripped
    assert app.international is False
    assert app.consent_terms is True and app.consent_sms is False
    assert app.consent_version == "2026-09-08"
    assert app.answers["purpose"] == "Grow my brand"
    assert "userAgent" not in app.answers and app.user_agent == "pytest"
    kinds = [e.kind for e in app.events]
    assert kinds == ["applied"]


def test_resubmit_updates_same_row(db, fakes):
    client.post("/api/applications/", json=FORM)
    r = client.post("/api/applications/", json={**FORM, "sport": "Field Hockey", "year": "Senior"})
    assert r.json()["created"] is False
    rows = db.query(Application).all()
    assert len(rows) == 1
    assert rows[0].sport == "Field Hockey" and rows[0].submit_count == 2
    assert [e.kind for e in rows[0].events] == ["applied", "resubmitted"]


def test_resubmit_never_resets_status(db, fakes):
    client.post("/api/applications/", json=FORM)
    app = db.query(Application).one()
    client.post(f"/api/applications/{app.id}/approve", headers=AUTH, json={"by": "reviewer"})
    client.post("/api/applications/", json=FORM)
    db.expire_all()
    assert db.query(Application).one().status == "agreement_sent"


def test_intake_links_existing_ambassador(db, fakes):
    db.add(Ambassador(ig_username="jane.doe", status="candidate", source="admin"))
    db.commit()
    client.post("/api/applications/", json=FORM)
    app = db.query(Application).one()
    assert app.ambassador_id is not None


def test_intake_requires_email(db, fakes):
    r = client.post("/api/applications/", json={k: v for k, v in FORM.items() if k not in ("email", "collegeEmail")})
    assert r.status_code == 400


def test_honeypot_swallows_bots(db, fakes):
    r = client.post("/api/applications/", json={**FORM, "website": "http://spam"})
    assert r.status_code == 200
    assert db.query(Application).count() == 0


def test_rate_limit_per_ip(db, fakes):
    for i in range(apps_router._RATE_LIMIT):
        assert client.post("/api/applications/", json={**FORM, "email": f"a{i}@x.com"}).status_code == 200
    assert client.post("/api/applications/", json={**FORM, "email": "late@x.com"}).status_code == 429


def test_admin_routes_need_key(db):
    assert client.get("/api/applications/").status_code == 401   # header missing (401, not 422, since the env-aware dependency)
    assert client.get("/api/applications/", headers={"X-API-Key": "nope"}).status_code == 401
    assert client.get("/api/applications/summary", headers=AUTH).status_code == 200


# -- Review -> DocuSign -> Stripe -> accepted -------------------------------

def _apply(db) -> Application:
    client.post("/api/applications/", json=FORM)
    return db.query(Application).one()


def test_approve_sends_envelope(db, fakes):
    app = _apply(db)
    r = client.post(f"/api/applications/{app.id}/approve", headers=AUTH, json={"by": "reviewer"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "agreement_sent"
    assert body["docusign_envelope_id"] == "env-123"
    assert body["reviewed_by"] == "reviewer"
    f = fakes["envelopes"][0]
    assert f.email == "jane.doe@example.com" and f.name == "Jane Doe"
    assert f.school == "Duke University" and f.sport == "Lacrosse" and f.handle == "jane.doe"
    steps = {s["key"]: s for s in body["progress"]}
    assert steps["reviewed"]["state"] == "done"
    assert steps["agreement"]["state"] == "current" and "sent" in steps["agreement"]["detail"]


def test_approve_without_docusign_records_error_and_stays_approved(db, fakes, monkeypatch):
    monkeypatch.setattr(docusign, "is_configured", lambda: False)
    app = _apply(db)
    r = client.post(f"/api/applications/{app.id}/approve", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert any(e["kind"] == "error" for e in r.json()["events"])


def test_resend_agreement_reuses_envelope(db, fakes):
    app = _apply(db)
    client.post(f"/api/applications/{app.id}/approve", headers=AUTH)
    r = client.post(f"/api/applications/{app.id}/resend-agreement", headers=AUTH)
    assert r.status_code == 200 and r.json()["mode"] == "docusign-resend"
    assert fakes["resent"] == ["env-123"] and len(fakes["envelopes"]) == 1


def test_decline_with_reason(db, fakes):
    app = _apply(db)
    r = client.post(f"/api/applications/{app.id}/decline", headers=AUTH,
                    json={"reason": "not on a roster", "notify": True})
    assert r.status_code == 200
    assert r.json()["status"] == "declined" and r.json()["decline_reason"] == "not on a roster"
    assert fakes["declined"] == ["jane.doe@example.com"]
    steps = {s["key"]: s for s in r.json()["progress"]}
    assert steps["reviewed"]["state"] == "blocked"
    # Declined can be re-approved.
    assert client.post(f"/api/applications/{app.id}/approve", headers=AUTH).json()["status"] == "agreement_sent"


def _connect_event(envelope_id="env-123", status="completed", email="jane.doe@example.com"):
    return {
        "event": f"envelope-{status}",
        "data": {
            "envelopeId": envelope_id,
            "envelopeSummary": {
                "status": status,
                "completedDateTime": "2026-09-09T15:04:05.1234567Z",
                "recipients": {"signers": [{"email": email, "name": "Jane Doe"}]},
                "customFields": {"textCustomFields": [{"name": "school", "value": "Duke University"}]},
            },
        },
    }


def _signed_docusign(raw: bytes) -> dict:
    secret = get_settings().docusign_connect_secret
    return {"X-DocuSign-Signature-1": base64.b64encode(hmac.new(secret.encode(), raw, hashlib.sha256).digest()).decode()}


def _signed_stripe(raw: bytes) -> dict:
    secret = get_settings().stripe_webhook_secret
    t = int(time.time())
    v1 = hmac.new(secret.encode(), f"{t}.".encode() + raw, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={t},v1={v1}"}


@pytest.fixture()
def secrets(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "docusign_connect_secret", "ds-secret")
    monkeypatch.setattr(s, "stripe_webhook_secret", "whsec_test")
    monkeypatch.setattr(s, "link_signing_secret", "link-secret")
    return s


def test_full_pipeline_to_accepted(db, fakes, secrets):
    app = _apply(db)
    client.post(f"/api/applications/{app.id}/approve", headers=AUTH)

    # DocuSign says completed -> signed -> Stripe account + link.
    raw = json.dumps(_connect_event()).encode()
    r = client.post("/api/applications/webhooks/docusign", content=raw,
                    headers={"Content-Type": "application/json", **_signed_docusign(raw)})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "stripe_pending"
    db.expire_all()
    app = db.query(Application).one()
    assert app.signed_at is not None and app.signed_at.year == 2026
    assert app.stripe_account_id == "acct_TEST1"
    assert app.stripe_requirements_due == ["external_account", "individual.dob.day"]
    email, meta = fakes["accounts"][0]
    assert email == "jane.doe@example.com"
    assert meta["envelope_id"] == "env-123" and meta["school"] == "Duke University"
    assert meta["program"] == pipeline.PROGRAM and meta["application_id"] == str(app.id)
    assert fakes["mail"] == [("jane.doe@example.com", "https://niltv.com/payouts/start/?t=TOKEN-acct_TEST1")]

    # Progress says what they still need.
    body = client.get(f"/api/applications/{app.id}", headers=AUTH).json()
    stripe_step = next(s for s in body["progress"] if s["key"] == "stripe")
    assert stripe_step["state"] == "current"
    assert "bank account" in stripe_step["detail"] and "date of birth" in stripe_step["detail"]
    assert body["payout_link"] == "https://niltv.com/payouts/start/?t=TOKEN-acct_TEST1"

    # Duplicate Connect delivery is a no-op.
    r = client.post("/api/applications/webhooks/docusign", content=raw,
                    headers={"Content-Type": "application/json", **_signed_docusign(raw)})
    assert r.json().get("note") == "already signed"
    assert len(fakes["accounts"]) == 1

    # Stripe: still missing something -> stays pending.
    evt = {"type": "account.updated", "data": {"object": {
        "id": "acct_TEST1", "payouts_enabled": False,
        "requirements": {"currently_due": ["individual.verification.document"], "past_due": []}}}}
    raw = json.dumps(evt).encode()
    r = client.post("/api/applications/webhooks/stripe", content=raw,
                    headers={"Content-Type": "application/json", **_signed_stripe(raw)})
    assert r.status_code == 200 and r.json()["status"] == "stripe_pending"
    db.expire_all()
    assert db.query(Application).one().stripe_requirements_due == ["individual.verification.document"]

    # Stripe: payouts enabled, nothing due -> accepted.
    evt["data"]["object"].update(payouts_enabled=True, requirements={"currently_due": [], "past_due": []})
    raw = json.dumps(evt).encode()
    r = client.post("/api/applications/webhooks/stripe", content=raw,
                    headers={"Content-Type": "application/json", **_signed_stripe(raw)})
    assert r.json()["status"] == "accepted"
    db.expire_all()
    app = db.query(Application).one()
    assert app.status == "accepted" and app.accepted_at is not None
    kinds = [e.kind for e in app.events]
    assert kinds == ["applied", "approved", "agreement_sent", "envelope_completed", "signed",
                     "stripe_account_created", "stripe_link_sent", "envelope_completed",
                     "stripe_updated", "stripe_updated", "accepted"]
    summary = client.get("/api/applications/summary", headers=AUTH).json()
    assert summary["by_status"]["accepted"] == 1 and summary["in_progress"] == 0


def test_international_skips_stripe(db, fakes, secrets):
    client.post("/api/applications/", json={**FORM, "international": "Yes"})
    app = db.query(Application).one()
    assert app.international is True
    client.post(f"/api/applications/{app.id}/approve", headers=AUTH)
    raw = json.dumps(_connect_event()).encode()
    r = client.post("/api/applications/webhooks/docusign", content=raw,
                    headers={"Content-Type": "application/json", **_signed_docusign(raw)})
    assert r.json()["status"] == "accepted"
    assert fakes["accounts"] == [] and fakes["mail"] == []
    body = client.get(f"/api/applications/{app.id}", headers=AUTH).json()
    assert next(s for s in body["progress"] if s["key"] == "stripe")["state"] == "skipped"


def test_accept_promotes_linked_ambassador(db, fakes, secrets):
    db.add(Ambassador(ig_username="jane.doe", status="candidate", source="admin"))
    db.commit()
    client.post("/api/applications/", json={**FORM, "international": "Yes"})
    app = db.query(Application).one()
    client.post(f"/api/applications/{app.id}/approve", headers=AUTH)
    raw = json.dumps(_connect_event()).encode()
    client.post("/api/applications/webhooks/docusign", content=raw,
                headers={"Content-Type": "application/json", **_signed_docusign(raw)})
    db.expire_all()
    assert db.query(Ambassador).filter(Ambassador.ig_username == "jane.doe").one().status == "confirmed"


def test_powerform_envelope_matches_by_email(db, fakes, secrets, monkeypatch):
    """PowerForm fallback: the envelope was never created by us, so Connect
    matches on the signer's email."""
    monkeypatch.setattr(docusign, "is_configured", lambda: False)
    monkeypatch.setattr(get_settings(), "docusign_powerform_url", "https://powerforms.docusign.net/x")
    monkeypatch.setattr(mailer, "send_powerform_agreement", lambda to, name, url: True)
    app = _apply(db)
    r = client.post(f"/api/applications/{app.id}/approve", headers=AUTH)
    assert r.json()["status"] == "agreement_sent" and r.json()["docusign_envelope_id"] is None
    raw = json.dumps(_connect_event(envelope_id="env-PF")).encode()
    r = client.post("/api/applications/webhooks/docusign", content=raw,
                    headers={"Content-Type": "application/json", **_signed_docusign(raw)})
    assert r.json()["status"] == "stripe_pending"
    db.expire_all()
    assert db.query(Application).one().docusign_envelope_id == "env-PF"


def test_webhooks_reject_bad_signatures(db, secrets):
    raw = json.dumps(_connect_event()).encode()
    assert client.post("/api/applications/webhooks/docusign", content=raw,
                       headers={"Content-Type": "application/json", "X-DocuSign-Signature-1": "nope"}).status_code == 401
    assert client.post("/api/applications/webhooks/docusign", content=raw,
                       headers={"Content-Type": "application/json"}).status_code == 401
    raw = json.dumps({"type": "account.updated"}).encode()
    assert client.post("/api/applications/webhooks/stripe", content=raw,
                       headers={"Content-Type": "application/json", "Stripe-Signature": "t=1,v1=bad"}).status_code == 401


def test_unknown_envelope_is_acknowledged(db, secrets):
    raw = json.dumps(_connect_event(envelope_id="env-other", email="nobody@x.com")).encode()
    r = client.post("/api/applications/webhooks/docusign", content=raw,
                    headers={"Content-Type": "application/json", **_signed_docusign(raw)})
    assert r.status_code == 200 and r.json()["status"] == "ignored"


def test_update_notes_and_filters(db, fakes):
    app = _apply(db)
    r = client.post(f"/api/applications/{app.id}/update", headers=AUTH,
                    json={"notes": "met at the showcase", "international": True})
    assert r.status_code == 200 and r.json()["notes"] == "met at the showcase" and r.json()["international"] is True
    assert client.get("/api/applications/?university=duke", headers=AUTH).json()[0]["id"] == app.id
    assert client.get("/api/applications/?sport=hockey", headers=AUTH).json() == []
    assert client.get("/api/applications/?q=@jane", headers=AUTH).json()[0]["id"] == app.id
    assert client.get("/api/applications/?status=open", headers=AUTH).json()[0]["id"] == app.id
    assert client.get("/api/applications/?status=bogus", headers=AUTH).status_code == 400


# -- Pure helpers -----------------------------------------------------------

def test_stripe_signature_helper(secrets):
    raw = b'{"x":1}'
    t = 1_700_000_000
    v1 = hmac.new(b"whsec_test", f"{t}.".encode() + raw, hashlib.sha256).hexdigest()
    assert stripe_connect.verify_webhook_signature(raw, f"t={t},v1={v1}", now=t + 10)
    assert not stripe_connect.verify_webhook_signature(raw, f"t={t},v1={v1}", now=t + 10_000)  # stale
    assert not stripe_connect.verify_webhook_signature(raw, f"t={t},v1=deadbeef", now=t)
    assert not stripe_connect.verify_webhook_signature(raw, None, now=t)


def test_lowercase_names_are_capitalised():
    assert pipeline.normalize_name("jordan") == "Jordan"
    assert pipeline.normalize_name("  taylor ") == "Taylor"
    assert pipeline.normalize_name("McKenna") == "McKenna"
    assert pipeline.normalize_name("DeShawn") == "DeShawn"
    assert docusign._greeting_name("jordan lee") == "Jordan"
    assert docusign._greeting_name("") == "there"
    assert docusign._greeting_name(None) == "there"


def test_email_layout_is_branded(secrets):
    out = mailer._layout("<p>Hi <b>x</b></p>", preheader="A <b>pre</b>")
    assert "niltv-logo-email.png" in out and 'alt="NIL TV"' in out
    assert "<p>Hi <b>x</b></p>" in out                      # body html passes through
    assert "A &lt;b&gt;pre&lt;/b&gt;" in out                # preheader is escaped
    assert "/contact/" in out and "Durham" in out


def test_create_envelope_sets_reply_to(monkeypatch, secrets):
    calls = []
    monkeypatch.setattr(docusign, "_api", lambda m, p, json=None: calls.append((m, p, json)) or {"envelopeId": "env-9"})
    s = get_settings()
    monkeypatch.setattr(s, "docusign_template_id", "tpl")
    monkeypatch.setattr(s, "docusign_reply_email", "contact@niltv.com")
    monkeypatch.setattr(s, "docusign_reply_name", "NIL TV")
    monkeypatch.setattr(s, "docusign_brand_id", "brand-1")
    assert docusign.create_envelope(docusign.EnvelopeFields(
        email="a@x.edu", name="jordan lee", school="Duke", sport="", handle="", application_id=1)) == "env-9"
    (_, path, payload), = calls
    assert path == "/envelopes"
    assert payload["emailSettings"] == {"replyEmailAddressOverride": "contact@niltv.com", "replyEmailNameOverride": "NIL TV"}
    assert payload["emailBlurb"].startswith("Hi Jordan,")
    assert payload["brandId"] == "brand-1"


def test_decline_voids_open_envelope(db, fakes, secrets, monkeypatch):
    voided = []
    monkeypatch.setattr(docusign, "void_envelope", lambda env_id, reason: voided.append((env_id, reason)))
    app, _ = pipeline.intake(db, FORM, notify=False)
    pipeline.approve(db, app, by="staff")
    assert app.status == "agreement_sent" and app.docusign_envelope_id
    pipeline.decline(db, app, reason="test", by="staff")
    assert voided == [(app.docusign_envelope_id, "Application declined")]
    assert app.status == "declined" and app.docusign_status == "voided"
    assert "envelope_voided" in [e.kind for e in app.events]


def test_create_express_account_uses_accounts_v2(monkeypatch, secrets):
    """Creation is a v2 call (recipient config, Express dashboard); the manual
    payout schedule is the v1 update whose v1-shaped response is returned."""
    calls = []

    def _api(method, path, data=None, json=None):
        calls.append((method, path, data, json))
        if path == "/v2/core/accounts":
            return {"id": "acct_V2", "object": "v2.core.account"}
        return {"id": "acct_V2", "payouts_enabled": False, "requirements": {"currently_due": ["external_account"]}}
    monkeypatch.setattr(stripe_connect, "_api", _api)

    acct = stripe_connect.create_express_account("a@x.edu", {"school": "Duke", "sport": ""}, name="Ada Lovelace")
    assert acct["id"] == "acct_V2" and acct["requirements"]["currently_due"] == ["external_account"]
    (m1, p1, d1, j1), (m2, p2, d2, j2) = calls
    assert (m1, p1, d1) == ("POST", "/v2/core/accounts", None)
    assert j1["dashboard"] == "express" and j1["display_name"] == "Ada Lovelace" and j1["contact_email"] == "a@x.edu"
    assert j1["identity"] == {"country": "us", "entity_type": "individual"}
    assert j1["configuration"]["recipient"]["capabilities"]["stripe_balance"]["stripe_transfers"] == {"requested": True}
    assert j1["defaults"]["responsibilities"] == {"fees_collector": "application", "losses_collector": "application"}
    assert j1["metadata"] == {"school": "Duke"}  # blanks dropped
    assert (m2, p2, j2) == ("POST", "/v1/accounts/acct_V2", None)
    assert d2 == {"settings[payouts][schedule][interval]": "manual"}


def test_payout_token_matches_lambda_scheme(secrets):
    token = stripe_connect.payout_token("acct_ABC")
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
    acct, sig = raw.rsplit(".", 1)
    assert acct == "acct_ABC" and len(sig) == 24
    assert sig == hmac.new(b"link-secret", b"acct_ABC", hashlib.sha256).hexdigest()[:24]
    assert stripe_connect.payout_link("acct_ABC").startswith("https://niltv.com/payouts/start/?t=")


def test_handle_and_international_normalizers():
    assert pipeline.normalize_handle("https://www.instagram.com/Jane.Doe/?hl=en") == "jane.doe"
    assert pipeline.normalize_handle("@bob_22 ") == "bob_22"
    assert pipeline.normalize_handle("") is None
    assert pipeline._international("Yes") is True
    assert pipeline._international("No, I am a US citizen") is False
    assert pipeline._international("") is None
    assert pipeline._humanize("individual.verification.document") == "ID document"
    assert pipeline._humanize("individual.address.city") == "address"


def test_resolve_base_uri_prefers_setting(monkeypatch):
    monkeypatch.setattr(get_settings(), "docusign_base_uri", "https://na9.docusign.net/")
    assert docusign.resolve_base_uri() == "https://na9.docusign.net"


def test_resolve_base_uri_via_userinfo(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "docusign_base_uri", "")
    monkeypatch.setattr(s, "docusign_account_id", "ACC-2")
    monkeypatch.setattr(docusign, "access_token", lambda: "tok")
    docusign._base_uri_cache.clear()

    class R:
        status_code = 200
        text = ""

        def json(self):
            return {"accounts": [
                {"account_id": "acc-1", "is_default": True, "base_uri": "https://na3.docusign.net"},
                {"account_id": "acc-2", "is_default": False, "base_uri": "https://na4.docusign.net"},
            ]}

    monkeypatch.setattr(docusign.httpx, "get", lambda *a, **k: R())
    assert docusign.resolve_base_uri() == "https://na4.docusign.net"
    docusign._base_uri_cache.clear()
    monkeypatch.setattr(s, "docusign_account_id", "nope")
    with pytest.raises(docusign.DocuSignError):
        docusign.resolve_base_uri()
    docusign._base_uri_cache.clear()


# -- Backfill intake --------------------------------------------------------

def test_backfill_intake_backdates_and_skips_consent(db, fakes, monkeypatch):
    from datetime import datetime, timezone
    called = []
    monkeypatch.setattr(mailer, "notify_staff_new_applicant", lambda *a, **k: called.append(1) or True)
    payload = {"email": "old@athlete.edu", "firstName": "Old", "lastName": "Timer", "university": "Duke University",
               "sport": "Rowing", "source": "google-form", "consentVersion": "google-form-legacy",
               "submittedAt": "6/4/2026 16:09:36", "formTab": "Form Responses 2"}
    at = datetime(2026, 6, 4, 16, 9, 36, tzinfo=timezone.utc)
    app, created = pipeline.intake(db, payload, source="google-form", applied_at=at, notify=False)
    assert created and app.source == "google-form"
    assert app.created_at == at and app.consent_at is None and app.consent_version == "google-form-legacy"
    assert app.consent_terms is False
    assert [e.kind for e in app.events] == ["applied"] and app.events[0].at == at
    assert app.events[0].detail["tab"] == "Form Responses 2"
    assert called == []  # no staff email during backfill
    # A later website submission by the same athlete stamps consent and keeps the applied date.
    client.post("/api/applications/", json={**FORM, "email": "old@athlete.edu"})
    db.expire_all()
    app = db.query(Application).filter(Application.email == "old@athlete.edu").one()
    assert app.created_at == at and app.consent_at is not None and app.submit_count == 2


# -- Spelling guard, approve gate, account requirement -----------------------

def test_intake_canonicalizes_school_and_channel(db, fakes):
    r = client.post("/api/applications/", json={**FORM, "university": "duke", "campusChannel": "", "rosterLink": "https://goduke.com/x"})
    assert r.status_code == 200
    app = db.query(Application).one()
    assert app.university == "Duke University" and app.campus_channel == "truebluetv"
    assert app.answers["universityAsTyped"] == "duke" and app.answers["universityMatched"] is True
    body = client.get(f"/api/applications/{app.id}", headers=AUTH).json()
    assert body["campus_channel_label"] == "TrueBlue TV" and body["missing_for_approval"] == []


def test_approve_gate_blocks_missing_roster_link(db, fakes):
    client.post("/api/applications/", json={k: v for k, v in FORM.items() if k != "rosterLink"})
    app = db.query(Application).one()
    body = client.get(f"/api/applications/{app.id}", headers=AUTH).json()
    assert body["missing_for_approval"] == ["roster link"]
    r = client.post(f"/api/applications/{app.id}/approve", headers=AUTH)
    assert r.status_code == 409 and "roster link" in r.json()["detail"]
    client.post(f"/api/applications/{app.id}/update", headers=AUTH, json={"roster_link": "https://example.edu/roster/jane"})
    assert client.post(f"/api/applications/{app.id}/approve", headers=AUTH).status_code == 200


def test_account_required_when_pools_configured(db, fakes, monkeypatch):
    from backend.onboarding import cognito
    monkeypatch.setattr(get_settings(), "cognito_user_pools", "us-east-1_test:client")
    r = client.post("/api/applications/", json=FORM)
    assert r.status_code == 401
    # a verified account: its email wins over the body's
    monkeypatch.setattr(cognito, "verify", lambda tok: cognito.Account(sub="abc", email="acct@x.com", email_verified=True, pool_id="us-east-1_test"))
    r = client.post("/api/applications/", json=FORM, headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    app = db.query(Application).one()
    assert app.email == "acct@x.com" and app.answers["account"]["sub"] == "abc"


def test_received_email_only_on_create(db, fakes, monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send_application_received", lambda to, name: sent.append(to) or True)
    client.post("/api/applications/", json=FORM)
    client.post("/api/applications/", json=FORM)
    assert sent == ["jane.doe@example.com"]


def test_summary_counts(db, fakes):
    client.post("/api/applications/", json=FORM)
    # explicit channel wins; a blank one is inferred from the school
    client.post("/api/applications/", json={**FORM, "email": "b@x.com", "university": "Baylor", "sport": "Softball", "campusChannel": ""})
    s = client.get("/api/applications/summary", headers=AUTH).json()
    assert s["by_school"] == {"Baylor University": 1, "Duke University": 1}
    assert s["by_sport"] == {"Lacrosse": 1, "Softball": 1}
    assert s["by_channel"]["truebluetv"] == {"label": "TrueBlue TV", "count": 1}
    assert s["by_channel"]["brazostv"] == {"label": "Brazos TV", "count": 1}
    assert s["applied_this_month"] == 2
