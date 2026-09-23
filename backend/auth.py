"""API key authentication dependency for FastAPI."""

import hmac
from typing import Optional

from fastapi import Header, HTTPException

from backend.config import get_settings


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
