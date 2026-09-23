"""Verify NIL TV site account tokens (Cognito ID tokens) on the public intake.

The signup form only shows for a signed-in niltv.com account and sends the
account's ID token as ``Authorization: Bearer <jwt>``. We verify it against
the pools listed in ``COGNITO_USER_POOLS`` ("<poolId>:<clientId>", comma
separated, so several pools can be valid at once) and use the token's email
as the application email. With no pools configured the account check is
skipped, so nothing breaks before the env is set.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from backend.config import get_settings

log = logging.getLogger(__name__)


class TokenError(ValueError):
    pass


@dataclass
class Account:
    sub: str
    email: str
    email_verified: bool
    pool_id: str


def pools() -> list[tuple[str, str]]:
    """[(pool_id, client_id), ...] from COGNITO_USER_POOLS."""
    out = []
    for item in (get_settings().cognito_user_pools or "").split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        pool, client = item.split(":", 1)
        out.append((pool.strip(), client.strip()))
    return out


def required() -> bool:
    return bool(pools())


_jwks_clients: dict[str, object] = {}


def _jwks(pool_id: str):
    import jwt  # PyJWT

    if pool_id not in _jwks_clients:
        region = pool_id.split("_")[0]
        url = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/jwks.json"
        _jwks_clients[pool_id] = jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)
    return _jwks_clients[pool_id]


def verify(token: Optional[str]) -> Account:
    """Return the account behind a Cognito ID token, or raise TokenError."""
    import jwt

    if not token:
        raise TokenError("sign in required")
    try:
        header = jwt.get_unverified_header(token)
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError as e:
        raise TokenError(f"malformed token: {e}") from e
    iss = unverified.get("iss", "")
    match = next(((p, c) for p, c in pools() if iss.endswith("/" + p)), None)
    if match is None:
        raise TokenError("token is not from a NIL TV account pool")
    pool_id, client_id = match
    try:
        key = _jwks(pool_id).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, key.key, algorithms=[header.get("alg", "RS256")], audience=client_id,
            issuer=f"https://cognito-idp.{pool_id.split('_')[0]}.amazonaws.com/{pool_id}",
        )
    except jwt.PyJWTError as e:
        raise TokenError(f"invalid token: {e}") from e
    if claims.get("token_use") != "id":
        raise TokenError("expected an ID token")
    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise TokenError("account has no email")
    return Account(sub=claims.get("sub", ""), email=email,
                   email_verified=bool(claims.get("email_verified")), pool_id=pool_id)
