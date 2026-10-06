"""Signed-in request headers for tests: X-API-Key plus a session token for a
throwaway dashboard user with the given role (migration 029)."""

from backend.auth import hash_password, make_session_token
from backend.config import get_settings
from backend.database import SessionLocal
from backend.models import DashboardUser


def staff_user(role: str, username: str = "") -> DashboardUser:
    """Create (or reset) the test user and return it detached."""
    username = username or f"test-{role}"
    db = SessionLocal()
    try:
        user = db.query(DashboardUser).filter(DashboardUser.username == username).first()
        if user is None:
            user = DashboardUser(username=username, session_version=1)
            db.add(user)
        # Few iterations: these tests exercise the flow, not the hash cost.
        user.password_hash = hash_password("correct horse battery", iterations=1000)
        user.role = role
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user
    finally:
        db.close()


def session_headers(user: DashboardUser) -> dict:
    return {"X-API-Key": get_settings().api_key, "X-Dashboard-Session": make_session_token(user)}


def staff_headers(role: str, username: str = "") -> dict:
    return session_headers(staff_user(role, username))
