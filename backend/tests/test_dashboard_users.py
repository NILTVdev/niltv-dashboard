"""Individual dashboard accounts and roles (migration 029, backend/auth.py,
backend/routers/users.py):

* passwords are hashed and checked; session tokens are signed, expire, and
  stop working when the user's role or password changes or the user is removed;
* viewer < onboarding < admin is enforced on the API routes, not only in the UI;
* admins add / remove users and change roles, and cannot lock everyone out.
Runs in CI against the seeded Postgres (ENVIRONMENT=dev there).
"""

import time

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.config import get_settings
from backend.database import SessionLocal
from backend.main import app
from backend.models import DashboardUser
from backend.routers import users as users_router
from backend.tests._staff import session_headers, staff_headers, staff_user

client = TestClient(app)
KEY = {"X-API-Key": get_settings().api_key}
PASSWORD = "correct horse battery"   # what _staff sets


@pytest.fixture(autouse=True)
def clean():
    """Remove the u-* users these tests create; leave other modules' users alone."""
    def wipe():
        db = SessionLocal()
        try:
            db.query(DashboardUser).filter(DashboardUser.username.like("u-%")).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
    users_router._failures.clear()
    wipe()
    yield
    wipe()
    users_router._failures.clear()


# -- Passwords and tokens ---------------------------------------------------

def test_password_hash_round_trip():
    stored = auth.hash_password("s3cret-password", iterations=1000)
    assert stored.startswith("pbkdf2_sha256$1000$")
    assert auth.verify_password("s3cret-password", stored)
    assert not auth.verify_password("s3cret-passworD", stored)
    assert not auth.verify_password("x", "garbage")
    assert not auth.check_password_timing_safe("anything", None)


def test_session_token_is_signed_and_expires():
    user = staff_user("viewer", "u-token")
    token = auth.make_session_token(user)
    payload = auth.read_session_token(token)
    assert payload["uid"] == user.id and payload["r"] == "viewer"
    body, sig = token.split(".")
    assert auth.read_session_token(body + "." + "0" * len(sig)) is None
    assert auth.read_session_token(body[:-2] + "AA." + sig) is None
    assert auth.read_session_token("not-a-token") is None
    assert auth.read_session_token(token, now=time.time() + auth.SESSION_TTL + 1) is None


# -- Login --------------------------------------------------------------------

def test_login_issues_a_session_for_the_right_password():
    staff_user("onboarding", "u-jane")
    r = client.post("/api/auth/login", headers=KEY, json={"username": " U-Jane ", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["username"] == "u-jane" and body["user"]["role"] == "onboarding"
    me = client.get("/api/auth/me", headers={**KEY, "X-Dashboard-Session": body["token"]})
    assert me.status_code == 200 and me.json()["username"] == "u-jane"


def test_login_rejects_bad_credentials_and_needs_the_api_key():
    staff_user("viewer", "u-bob")
    assert client.post("/api/auth/login", json={"username": "u-bob", "password": PASSWORD}).status_code == 401
    assert client.post("/api/auth/login", headers=KEY, json={"username": "u-bob", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", headers=KEY, json={"username": "u-nobody", "password": PASSWORD}).status_code == 401


def test_login_locks_out_after_repeated_failures():
    staff_user("viewer", "u-brute")
    for _ in range(users_router._FAIL_LIMIT):
        client.post("/api/auth/login", headers=KEY, json={"username": "u-brute", "password": "wrong"})
    r = client.post("/api/auth/login", headers=KEY, json={"username": "u-brute", "password": PASSWORD})
    assert r.status_code == 429


def test_the_shared_login_is_gone():
    # The old DASHBOARD_PASSWORD is at most an API key now; it names no user,
    # and no dashboard route answers the key alone.
    assert client.get("/api/applications/", headers=KEY).status_code == 401
    assert client.get("/api/brand/accounts", headers=KEY).status_code == 401
    assert client.post("/api/auth/login", headers=KEY,
                       json={"username": "admin", "password": get_settings().api_key}).status_code == 401


# -- Role enforcement -----------------------------------------------------------

def test_viewer_gets_403_from_onboarding_and_admin_routes():
    viewer = staff_headers("viewer", "u-viewer")
    assert client.get("/api/applications/", headers=viewer).status_code == 403
    assert client.get("/api/applications/summary", headers=viewer).status_code == 403
    assert client.post("/api/applications/1/approve", headers=viewer).status_code == 403
    assert client.post("/api/applications/1/resend-agreement", headers=viewer).status_code == 403
    assert client.post("/api/applications/1/resend-stripe-link", headers=viewer).status_code == 403
    assert client.get("/api/users", headers=viewer).status_code == 403
    assert client.post("/api/web-analytics/pull", headers=viewer).status_code == 403
    # Data screens still work.
    assert client.get("/api/brand/accounts", headers=viewer).status_code == 200


def test_onboarding_user_runs_the_workflow_but_not_admin():
    onboarding = staff_headers("onboarding", "u-onb")
    assert client.get("/api/applications/", headers=onboarding).status_code == 200
    assert client.get("/api/applications/summary", headers=onboarding).status_code == 200
    assert client.get("/api/users", headers=onboarding).status_code == 403
    assert client.get("/api/reports/summary", headers=onboarding).status_code == 403
    assert client.post("/api/web-analytics/pull", headers=onboarding).status_code == 403


# -- User management -------------------------------------------------------------

def test_admin_adds_changes_and_removes_users():
    admin = staff_headers("admin", "u-admin")
    r = client.post("/api/users", headers=admin,
                    json={"username": "U-New", "password": "long enough pw", "role": "viewer"})
    assert r.status_code == 200 and r.json()["username"] == "u-new"
    new_id = r.json()["id"]
    assert client.post("/api/users", headers=admin,
                       json={"username": "u-new", "password": "long enough pw", "role": "viewer"}).status_code == 409
    assert client.post("/api/users", headers=admin,
                       json={"username": "u-short", "password": "short", "role": "viewer"}).status_code == 422
    assert client.post("/api/users", headers=admin,
                       json={"username": "u-bad", "password": "long enough pw", "role": "owner"}).status_code == 422
    assert "u-new" in [u["username"] for u in client.get("/api/users", headers=admin).json()]

    login = client.post("/api/auth/login", headers=KEY, json={"username": "u-new", "password": "long enough pw"})
    old = {**KEY, "X-Dashboard-Session": login.json()["token"]}
    assert client.get("/api/applications/", headers=old).status_code == 403

    r = client.post(f"/api/users/{new_id}/update", headers=admin, json={"role": "onboarding"})
    assert r.status_code == 200 and r.json()["role"] == "onboarding"
    # The pre-promotion token is retired everywhere, data routes included; a
    # fresh sign-in carries the new role.
    assert client.get("/api/applications/", headers=old).status_code == 401
    assert client.get("/api/brand/accounts", headers=old).status_code == 401
    login = client.post("/api/auth/login", headers=KEY, json={"username": "u-new", "password": "long enough pw"})
    fresh = {**KEY, "X-Dashboard-Session": login.json()["token"]}
    assert client.get("/api/applications/", headers=fresh).status_code == 200

    assert client.post(f"/api/users/{new_id}/delete", headers=admin).status_code == 200
    assert client.get("/api/auth/me", headers=fresh).status_code == 401
    assert client.get("/api/brand/accounts", headers=fresh).status_code == 401


def test_password_reset_signs_the_user_out():
    admin = staff_headers("admin", "u-admin")
    user = staff_user("viewer", "u-reset")
    before = session_headers(user)
    assert client.get("/api/auth/me", headers=before).status_code == 200
    r = client.post(f"/api/users/{user.id}/update", headers=admin, json={"password": "a brand new password"})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=before).status_code == 401
    assert client.post("/api/auth/login", headers=KEY,
                       json={"username": "u-reset", "password": "a brand new password"}).status_code == 200


def test_admins_cannot_lock_everyone_out(monkeypatch):
    admin_user = staff_user("admin", "u-admin")
    admin = session_headers(admin_user)
    assert client.post(f"/api/users/{admin_user.id}/delete", headers=admin).status_code == 409   # self
    other = staff_user("admin", "u-admin2")
    monkeypatch.setattr(users_router, "_admin_count", lambda db: 1)
    assert client.post(f"/api/users/{other.id}/update", headers=admin, json={"role": "viewer"}).status_code == 409
    assert client.post(f"/api/users/{other.id}/delete", headers=admin).status_code == 409
