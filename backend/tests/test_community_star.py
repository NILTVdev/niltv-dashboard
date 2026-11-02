"""Functional tests for Community Star applications (migration 032).

Runs in CI against the seeded Postgres. SES is never called: the mailer is
monkeypatched. Covers the form POST, one application per email, the
application window, the honeypot, validation, the rate limit, staff auth,
and the staff sheet rows.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.database import SessionLocal
from backend.jobs import export_community_star_sheet as export_job
from backend.main import app
from backend.models import CommunityStarApplication
from backend.onboarding import mailer
from backend.routers import community_star as cs

client = TestClient(app)
AUTH = {"X-API-Key": "test"}  # matches DASHBOARD_PASSWORD in the CI env
URL = "/api/community-star/applications"

# The body niltv.com/communitystar builds (communitystar/index.html, submit).
FORM = {
    "fullName": "Jane Doe",
    "email": "Jane.Doe@Example.com",
    "phone": "(919) 555-0100",
    "school": "Duke University",
    "schoolState": "NC",
    "schoolDomain": "duke.edu",
    "schoolMatched": True,
    "sport": "Women's Lacrosse",
    "classYear": "Jr",
    "instagram": "@Jane.Doe",
    "postUrl": "https://www.instagram.com/reels/DQ1abcXYZ_-/?igsh=xyz",
    "community": "Durham, NC",
    "work": "Weekly reading hour at the Durham library\r\nwith my teammates.",
    "organization": "Durham County Library",
    "collabInvited": True,
    "eligibleAndRules": True,
    "confirmAge": True,
    "consentPrivacy": True,
    "consentEmail": True,
    "consentSms": False,
    "consentPartners": False,
    "program": "community-star",
    "season": "2026",
    "source": "communitystar",
    "consentVersion": "2026-10-11",
    "submittedAt": "2026-11-02T15:00:00Z",
    "userAgent": "pytest",
    "utm": {"utm_source": "instagram"},
}


def _clean(db):
    db.query(CommunityStarApplication).delete()
    db.commit()


@pytest.fixture()
def db():
    session = SessionLocal()
    _clean(session)
    cs._hits.clear()
    yield session
    _clean(session)
    session.close()


@pytest.fixture()
def mail(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send_community_star_received", lambda to, name: sent.append((to, name)) or True)
    return sent


@pytest.fixture()
def window_open(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "community_star_opens", "2020-01-01T00:00:00+00:00")
    monkeypatch.setattr(s, "community_star_closes", "2099-01-01T00:00:00+00:00")


def test_post_stores_application_and_confirms(db, mail, window_open):
    r = client.post(URL, json=FORM)
    assert r.status_code == 200, r.text
    row = db.query(CommunityStarApplication).one()
    assert row.email == "jane.doe@example.com"
    assert row.instagram == "jane.doe"
    assert row.post_url == "https://www.instagram.com/reel/DQ1abcXYZ_-/"
    assert row.class_year == "Jr" and row.school_matched is True
    assert row.collab_invited and row.eligible_and_rules and row.confirm_age and row.consent_privacy
    assert row.consent_email is True and row.consent_sms is False
    assert row.utm == {"utm_source": "instagram"}
    assert row.answers["fullName"] == "Jane Doe"
    assert mail == [("jane.doe@example.com", "Jane")]
    db.refresh(row)
    assert row.confirmation_sent is True


def test_one_application_per_email(db, mail, window_open):
    assert client.post(URL, json=FORM).status_code == 200
    again = dict(FORM, email="JANE.DOE@example.com", fullName="Someone Else")
    r = client.post(URL, json=again)
    assert r.status_code == 409
    assert db.query(CommunityStarApplication).count() == 1
    assert db.query(CommunityStarApplication).one().full_name == "Jane Doe"


def test_one_application_per_instagram_account(db, mail, window_open):
    assert client.post(URL, json=FORM).status_code == 200
    r = client.post(URL, json=dict(FORM, email="jane.other@example.com", instagram="jane.doe"))
    assert r.status_code == 409
    assert "Instagram" in r.json()["detail"]
    assert db.query(CommunityStarApplication).count() == 1


def test_closed_outside_the_window(db, mail, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "community_star_opens", "2026-11-02T14:00:00+00:00")
    monkeypatch.setattr(s, "community_star_closes", "2026-11-24T08:00:00+00:00")
    assert cs.is_open(datetime(2026, 11, 2, 13, 59, tzinfo=timezone.utc)) is False
    assert cs.is_open(datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)) is True
    # 11:59pm PT on Nov 23 is still in; midnight PT is out
    assert cs.is_open(datetime(2026, 11, 24, 7, 59, 59, tzinfo=timezone.utc)) is True
    assert cs.is_open(datetime(2026, 11, 24, 8, 0, tzinfo=timezone.utc)) is False
    monkeypatch.setattr(s, "community_star_closes", "2021-01-01T00:00:00+00:00")
    r = client.post(URL, json=FORM)
    assert r.status_code == 410
    assert db.query(CommunityStarApplication).count() == 0


def test_honeypot_swallows_bots(db, mail, window_open):
    r = client.post(URL, json=dict(FORM, website="http://spam.example"))
    assert r.status_code == 200
    assert db.query(CommunityStarApplication).count() == 0
    assert mail == []


@pytest.mark.parametrize("change, message", [
    ({"email": "not-an-email"}, "email"),
    ({"fullName": " "}, "fullName"),
    ({"phone": "555-0100"}, "phone"),
    ({"classYear": "Senior"}, "classYear"),
    ({"instagram": "@bad handle!"}, "instagram"),
    ({"postUrl": "https://www.tiktok.com/@jane/video/1"}, "postUrl"),
    ({"postUrl": "https://instagram.com.evil.example/p/abc/"}, "postUrl"),
    ({"collabInvited": False}, "collabInvited"),
    ({"eligibleAndRules": "true"}, "eligibleAndRules"),
    ({"confirmAge": False}, "confirmAge"),
    ({"work": "x" * 1001}, "work"),
])
def test_validation(db, mail, window_open, change, message):
    r = client.post(URL, json=dict(FORM, **change))
    assert r.status_code == 400
    assert message in r.json()["detail"]
    assert db.query(CommunityStarApplication).count() == 0


def test_rate_limit_per_ip(db, mail, window_open):
    for i in range(cs._RATE_LIMIT):
        assert client.post(URL, json=dict(FORM, email=f"a{i}@example.com", instagram=f"a{i}")).status_code == 200
    r = client.post(URL, json=dict(FORM, email="late@example.com", instagram="late"))
    assert r.status_code == 429


def test_staff_routes_need_key(db, mail, window_open):
    client.post(URL, json=FORM)
    assert client.get(URL).status_code == 401
    rows = client.get(URL, headers=AUTH).json()
    assert [r["email"] for r in rows] == ["jane.doe@example.com"]
    summary = client.get("/api/community-star/summary", headers=AUTH).json()
    assert summary["total"] == 1 and summary["window"]["open"] is True


def test_sheet_rows(db, mail, window_open, monkeypatch):
    client.post(URL, json=FORM)
    written = {}
    monkeypatch.setattr(get_settings(), "community_star_sheet_id", "sheet-123")
    monkeypatch.setattr(export_job.sheets, "write_table",
                        lambda sid, tab, header, rows: written.update(sid=sid, tab=tab, header=header, rows=rows) or len(rows))
    assert export_job.export_community_star(db) == 1
    assert written["sid"] == "sheet-123" and written["tab"] == "Community Star"
    row = dict(zip(written["header"], written["rows"][0]))
    assert row["Email"] == "jane.doe@example.com"
    assert row["Instagram"] == "@jane.doe"
    assert row["Application post"] == "https://www.instagram.com/reel/DQ1abcXYZ_-/"
    assert row["18+"] == "yes" and row["SMS opt-in"] == ""
    assert row["UTM"] == "utm_source=instagram"


def test_sheet_falls_back_to_applications_sheet(db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "community_star_sheet_id", "")
    monkeypatch.setattr(s, "applications_sheet_id", "apps-sheet")
    seen = []
    monkeypatch.setattr(export_job.sheets, "write_table", lambda sid, tab, header, rows: seen.append((sid, tab)) or 0)
    export_job.export_community_star(db)
    assert seen == [("apps-sheet", "Community Star")]
