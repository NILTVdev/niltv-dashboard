"""Dashboard accounts: password hashing and what each role may call.

Roles
  admin    everything: onboarding, uploads, reports, user management
  general  analytics pages including the athlete roster; read-only
  demo     aggregate analytics only; read-only

The Next.js layer signs a session per account and forwards the account id
as ``X-Dashboard-User`` alongside the shared API key; ``backend.auth``
loads the account on every call and applies ``allowed()``. A call with the
key but no account header is a service caller (deploy probe, scripts) and
keeps full access, as before.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

ROLES = ("admin", "general", "demo")

# scrypt cost: ~16 MB, ~50 ms per hash. Stored with the hash so it can rise later.
_N, _R, _P = 2 ** 14, 8, 1
MIN_PASSWORD = 10

# Read-only API prefixes for each non-admin role. Admins (and service
# callers) are not limited. Everything not listed is admin-only, so a new
# router is closed to general/demo until it is added here.
_AGGREGATE = (
    "/api/zoomph",
    "/api/trueblue",
    "/api/brand",
    "/api/network-screen",
    "/api/campus-channels",
    "/api/web-analytics",
)
_ROSTER = ("/api/athletes", "/api/snapshots", "/api/posts")
READ_PREFIXES = {
    "general": _AGGREGATE + _ROSTER,
    "demo": _AGGREGATE,
}
# Inside an allowed prefix but still admin-only (account registry, tokens).
ADMIN_ONLY_PREFIXES = ("/api/brand/accounts",)
# Every signed-in account may read itself and change its own password.
SELF_SERVICE = {("GET", "/api/auth/me"), ("POST", "/api/auth/password")}


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def allowed(role: str, method: str, path: str) -> bool:
    """May an account with ``role`` make this call?"""
    path = path.rstrip("/") or "/"
    if (method, path) in SELF_SERVICE:
        return True
    if role == "admin":
        return True
    if method not in ("GET", "HEAD"):
        return False
    if any(_under(path, p) for p in ADMIN_ONLY_PREFIXES):
        return False
    return any(_under(path, p) for p in READ_PREFIXES.get(role, ()))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt),
                             n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


def check_password_rules(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"Password must be at least {MIN_PASSWORD} characters")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()
