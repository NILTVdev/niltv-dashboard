"""Dashboard accounts: hashing, role policy on the API, login, user management."""

import pytest
from fastapi.testclient import TestClient

from backend import accounts
from backend.database import SessionLocal
from backend.main import app
from backend.models import DashboardUser
from backend.routers import users as users_router

client = TestClient(app)
KEY = {"X-API-Key": "test"}
PW = "correct horse battery"


def _clean(db):
    db.query(DashboardUser).delete()
    db.commit()


@pytest.fixture()
def db():
    session = SessionLocal()
    _clean(session)
    users_router._fails.clear()
    yield session
    _clean(session)
    session.close()


def _user(db, email, role, active=True):
    u = DashboardUser(email=email, name=email.split("@")[0], role=role,
                      password_hash=accounts.hash_password(PW), active=active)
    db.add(u)
    db.commit()
    return u


def _as(user):
    return {**KEY, "X-Dashboard-User": str(user.id)}


def test_password_hash_roundtrip():
    h = accounts.hash_password(PW)
    assert h.startswith("scrypt$") and PW not in h
    assert accounts.verify_password(PW, h)
    assert not accounts.verify_password("wrong password", h)
    assert not accounts.verify_password(PW, "garbage")


@pytest.mark.parametrize("role,method,path,ok", [
    ("admin", "POST", "/api/applications/1/approve", True),
    ("general", "GET", "/api/athletes/", True),
    ("general", "GET", "/api/zoomph/summary", True),
    ("general", "GET", "/api/applications/", False),
    ("general", "POST", "/api/web-analytics/pull", False),
    ("general", "GET", "/api/brand/accounts", False),
    ("general", "GET", "/api/users/", False),
    ("demo", "GET", "/api/network-screen/summary", True),
    ("demo", "GET", "/api/athletes/", False),
    ("demo", "GET", "/api/snapshots/athletes/3", False),
    ("demo", "GET", "/api/reports/summary", False),
    ("demo", "GET", "/api/zoomphx", False),
    ("demo", "GET", "/api/auth/me", True),
    ("demo", "POST", "/api/auth/password", True),
])
def test_role_policy(role, method, path, ok):
    assert accounts.allowed(role, method, path) is ok


def test_api_enforces_role_and_active(db):
    demo = _user(db, "demo@niltv.com", "demo")
    general = _user(db, "general@niltv.com", "general")
    gone = _user(db, "gone@niltv.com", "admin", active=False)

    assert client.get("/api/athletes/", headers=_as(demo)).status_code == 403
    assert client.get("/api/applications/", headers=_as(general)).status_code == 403
    assert client.get("/api/athletes/", headers=_as(general)).status_code == 200
    assert client.get("/api/athletes/", headers=_as(gone)).status_code == 401
    assert client.get("/api/athletes/", headers={**KEY, "X-Dashboard-User": "999999"}).status_code == 401
    assert client.get("/api/athletes/", headers=KEY).status_code == 200  # service caller


def test_login_me_and_lockout(db):
    u = _user(db, "staff@niltv.com", "admin")
    r = client.post("/api/auth/login", headers=KEY, json={"email": " Staff@NILTV.com ", "password": PW})
    assert r.status_code == 200 and r.json()["role"] == "admin" and "password_hash" not in r.json()
    assert client.get("/api/auth/me", headers=_as(u)).json()["email"] == "staff@niltv.com"
    for _ in range(users_router._FAIL_LIMIT):
        assert client.post("/api/auth/login", headers=KEY, json={"email": u.email, "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", headers=KEY, json={"email": u.email, "password": PW}).status_code == 429


def test_login_unknown_or_disabled_email_fails_the_same_way(db):
    _user(db, "gone@niltv.com", "general", active=False)
    for email in ("nobody@niltv.com", "gone@niltv.com"):
        r = client.post("/api/auth/login", headers=KEY, json={"email": email, "password": PW})
        assert r.status_code == 401 and r.json()["detail"] == "Invalid email or password"


def test_failed_login_list_drops_aged_out_emails(db, monkeypatch):
    monkeypatch.setattr(users_router, "_FAIL_KEYS_PRUNE", 2)
    for i in range(3):
        client.post("/api/auth/login", headers=KEY, json={"email": f"x{i}@niltv.com", "password": "nope"})
    assert len(users_router._fails) == 3  # all still inside the window
    for d in users_router._fails.values():
        d[-1] -= users_router._FAIL_WINDOW + 1  # age every failure out
    client.post("/api/auth/login", headers=KEY, json={"email": "y@niltv.com", "password": "nope"})
    assert list(users_router._fails) == ["y@niltv.com"]


def test_shared_login_calls_stop_once_an_admin_exists(db):
    boot = {**KEY, "X-Dashboard-Bootstrap": "1"}
    assert client.get("/api/users/", headers=boot).status_code == 200
    _user(db, "first@niltv.com", "admin")
    assert client.get("/api/users/", headers=boot).status_code == 401
    # Plain service callers (scripts, the deploy probe) are unaffected.
    assert client.get("/api/users/", headers=KEY).status_code == 200


def test_status_counts_active_admins(db):
    assert client.get("/api/auth/status", headers=KEY).json() == {"active_admins": 0}
    _user(db, "a@niltv.com", "admin")
    _user(db, "d@niltv.com", "admin", active=False)
    assert client.get("/api/auth/status", headers=KEY).json() == {"active_admins": 1}


def test_admin_manages_users_and_keeps_one_admin(db):
    admin = _user(db, "boss@niltv.com", "admin")
    general = _user(db, "general@niltv.com", "general")

    r = client.post("/api/users/", headers=_as(admin),
                    json={"email": "New@NILTV.com", "name": "New Person", "role": "admin", "password": PW})
    assert r.status_code == 200 and r.json()["email"] == "new@niltv.com" and r.json()["created_by"] == "boss@niltv.com"
    assert client.post("/api/users/", headers=_as(admin),
                       json={"email": "new@niltv.com", "name": "x", "role": "admin", "password": PW}).status_code == 409
    assert client.post("/api/users/", headers=_as(admin),
                       json={"email": "s@niltv.com", "name": "x", "role": "admin", "password": "short"}).status_code == 400
    assert client.get("/api/users/", headers=_as(general)).status_code == 403

    new_id = r.json()["id"]
    assert client.post(f"/api/users/{admin.id}/update", headers=_as(admin), json={"role": "demo"}).status_code == 409
    assert client.post(f"/api/users/{new_id}/update", headers=_as(admin), json={"active": False}).json()["active"] is False
    # boss is now the only active admin
    assert client.post(f"/api/users/{admin.id}/update", headers=KEY, json={"active": False}).status_code == 409


def test_change_own_password(db):
    u = _user(db, "me@niltv.com", "demo")
    bad = client.post("/api/auth/password", headers=_as(u), json={"current_password": "nope", "new_password": "a much longer one"})
    assert bad.status_code == 400
    ok = client.post("/api/auth/password", headers=_as(u), json={"current_password": PW, "new_password": "a much longer one"})
    assert ok.status_code == 200
    db.refresh(u)
    assert accounts.verify_password("a much longer one", u.password_hash)
