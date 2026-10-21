"""API key + dashboard account authentication for FastAPI."""

import hmac
from typing import Optional

from fastapi import Header, HTTPException, Request

from backend import accounts
from backend.config import get_settings
from backend.database import SessionLocal
from backend.models import DashboardUser


async def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    x_dashboard_user: Optional[str] = Header(None, alias="X-Dashboard-User"),
    x_dashboard_bootstrap: Optional[str] = Header(None, alias="X-Dashboard-Bootstrap"),
    x_dashboard_session_version: Optional[str] = Header(None, alias="X-Dashboard-Session-Version"),
) -> str:
    """Validate the X-API-Key header against the configured API key
    (DASHBOARD_API_KEY, falling back to DASHBOARD_PASSWORD), then apply the
    caller's account role.

    The dashboard forwards the signed-in account's id as X-Dashboard-User and
    the session's version as X-Dashboard-Session-Version. The account must
    exist, be active and still be on that version (a password change, reset
    or disable bumps it, ending older sessions), and its role must allow the
    call (backend.accounts.allowed). No header = a service caller (deploy probe,
    scripts), which keeps full access. The account is left on
    ``request.state.dashboard_user`` (None for service callers).

    X-Dashboard-Bootstrap marks a call made under the shared env login, which
    only exists to create the first admin: it is refused once an active admin
    account exists, even if that session's cookie hasn't expired.

    ENVIRONMENT=local skips the check entirely — Settings.validate_environment
    guarantees that mode only ever runs against a database on this machine.

    Constant-time comparison: a plain ``!=`` short-circuits
    on the first mismatching byte, which leaks key prefixes to a timing attacker.
    """
    settings = get_settings()
    request.state.dashboard_user = None
    if settings.auth_disabled:
        return "local"
    if x_api_key is None:
        raise HTTPException(status_code=401, detail="Missing API key")
    if not hmac.compare_digest(x_api_key.encode(), settings.api_key.encode()):
        raise HTTPException(status_code=401, detail="Invalid API key")
    if x_dashboard_user:
        user = _load_user(x_dashboard_user)
        if user is None:
            raise HTTPException(status_code=401, detail="Account not found or disabled")
        if x_dashboard_session_version != str(user.session_version):
            raise HTTPException(status_code=401, detail="This session has ended. Sign in again.")
        if not accounts.allowed(user.role, request.method, request.url.path):
            raise HTTPException(status_code=403, detail="Your account does not have access to this")
        request.state.dashboard_user = user
    elif x_dashboard_bootstrap and _admin_exists():
        raise HTTPException(status_code=401, detail="The shared login closed when the first admin account was created. Sign in with your own account.")
    return x_api_key


def _admin_exists() -> bool:
    db = SessionLocal()
    try:
        q = db.query(DashboardUser.id).filter(DashboardUser.role == "admin", DashboardUser.active.is_(True))
        return q.first() is not None
    finally:
        db.close()


def _load_user(raw_id: str) -> Optional[DashboardUser]:
    if not raw_id.isdigit():
        return None
    db = SessionLocal()
    try:
        user = db.query(DashboardUser).filter(DashboardUser.id == int(raw_id)).first()
        if user is None or not user.active:
            return None
        db.expunge(user)
        return user
    finally:
        db.close()


def actor_name(request: Request, default: str = "staff") -> str:
    """Who to record for a staff action: the signed-in account's email, else ``default``."""
    user = getattr(request.state, "dashboard_user", None)
    return user.email if user is not None else default
