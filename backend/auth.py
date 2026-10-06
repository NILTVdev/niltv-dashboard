"""Authentication for the dashboard API.

Two layers, both checked on every dashboard route:

* ``require_api_key`` — the X-API-Key header proves the call comes from the
  dashboard's Next.js server (the key never reaches a browser).
* ``require_role(...)`` — the X-Dashboard-Session header names the person
  behind the call. The token is issued by POST /api/auth/login, signed with
  the API key, and re-checked against dashboard_users on every request, so a
  removed user or a changed role takes effect immediately.

Roles are ordered: viewer < onboarding < admin.

Session token: ``<base64url(json payload)>.<hex HMAC-SHA256>`` where the HMAC
key is the API key and the signed data is ``"dashboard-session." + payload``.
frontend/lib/session.ts verifies the same format in the Edge middleware.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from types import SimpleNamespace
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import get_db

ROLES = ("viewer", "onboarding", "admin")
_RANK = {r: i for i, r in enumerate(ROLES)}

SESSION_TTL = 7 * 24 * 3600          # matches the auth_token cookie maxAge
_SESSION_PREFIX = b"dashboard-session."

_PBKDF2_ITERATIONS = 600_000


async def require_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> str:
    """Validate the X-API-Key header against the configured API key
    (DASHBOARD_API_KEY, falling back to DASHBOARD_PASSWORD).

    ENVIRONMENT=local skips the check entirely — Settings.validate_environment
    guarantees that mode only ever runs against a database on this machine.

    Constant-time comparison: a plain ``!=`` short-circuits
    on the first mismatching byte, which leaks key prefixes to a timing attacker.
    """
    settings = get_settings()
    if settings.auth_disabled:
        return "local"
    if x_api_key is None:
        raise HTTPException(status_code=401, detail="Missing API key")
    if not hmac.compare_digest(x_api_key.encode(), settings.api_key.encode()):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


# -- Passwords --------------------------------------------------------------

def hash_password(password: str, iterations: int = _PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# A real hash to check against when the username does not exist, so a login
# for an unknown user costs the same time as one with a wrong password.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def check_password_timing_safe(password: str, stored: Optional[str]) -> bool:
    ok = verify_password(password, stored or _DUMMY_HASH)
    return ok and stored is not None


# -- Session tokens ---------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload_b64: str) -> str:
    key = get_settings().api_key.encode()
    return hmac.new(key, _SESSION_PREFIX + payload_b64.encode(), hashlib.sha256).hexdigest()


def make_session_token(user, now: Optional[float] = None) -> str:
    now = int(now if now is not None else time.time())
    payload = {"uid": user.id, "u": user.username, "r": user.role,
               "v": user.session_version, "exp": now + SESSION_TTL}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def read_session_token(token: str, now: Optional[float] = None) -> Optional[dict]:
    """The payload of a correctly signed, unexpired token, else None."""
    try:
        body, sig = token.split(".")
        if not hmac.compare_digest(sig, _sign(body)):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < (now if now is not None else time.time()):
        return None
    return payload


# -- Dependencies -----------------------------------------------------------

LOCAL_USER = SimpleNamespace(id=None, username="local", role="admin", session_version=0)


def current_user(
    x_dashboard_session: Optional[str] = Header(None, alias="X-Dashboard-Session"),
    db: Session = Depends(get_db),
):
    """The dashboard user behind the request, loaded fresh from the database.
    ENVIRONMENT=local has no logins: every request is the local admin."""
    from backend.models import DashboardUser

    if get_settings().auth_disabled:
        return LOCAL_USER
    if not x_dashboard_session:
        raise HTTPException(status_code=401, detail="Sign in required")
    payload = read_session_token(x_dashboard_session)
    user = db.get(DashboardUser, payload["uid"]) if payload else None
    if user is None or user.session_version != payload.get("v"):
        raise HTTPException(status_code=401, detail="Session expired, sign in again")
    return user


def has_role(user, minimum: str) -> bool:
    return _RANK.get(user.role, -1) >= _RANK[minimum]


def require_role(minimum: str):
    """Dependency factory: 403 unless the signed-in user has at least `minimum`."""
    if minimum not in _RANK:
        raise ValueError(f"unknown role {minimum!r}")

    def _check(user=Depends(current_user)):
        if not has_role(user, minimum):
            raise HTTPException(status_code=403, detail=f"Requires the {minimum} role")
        return user

    return _check
