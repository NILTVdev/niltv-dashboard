"""Site account tokens on the public intake: only RS256 tokens signed by the pool's key pass."""

import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.config import get_settings
from backend.onboarding import cognito

POOL, CLIENT = "us-east-1_TestPool", "test-client"
ISS = f"https://cognito-idp.us-east-1.amazonaws.com/{POOL}"
PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC = PRIVATE.public_key()


class _Key:
    key = PUBLIC


class _Jwks:
    def get_signing_key_from_jwt(self, token):
        return _Key()


@pytest.fixture(autouse=True)
def pool(monkeypatch):
    monkeypatch.setattr(get_settings(), "cognito_user_pools", f"{POOL}:{CLIENT}")
    monkeypatch.setattr(cognito, "_jwks", lambda pool_id: _Jwks())


def _claims(**over):
    now = int(time.time())
    return {"iss": ISS, "aud": CLIENT, "token_use": "id", "sub": "abc", "email": "Jane@Example.com",
            "email_verified": True, "iat": now, "exp": now + 600, **over}


def test_valid_rs256_token_passes():
    token = jwt.encode(_claims(), PRIVATE, algorithm="RS256")
    account = cognito.verify(token)
    assert account.email == "jane@example.com" and account.pool_id == POOL


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_token_choosing_hmac_with_the_public_key_is_refused():
    # Classic algorithm confusion: HS256 "signed" with the pool's public key as the secret.
    pem = PUBLIC.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps(_claims()).encode())
    sig = _b64(hmac.new(pem, f"{head}.{body}".encode(), hashlib.sha256).digest())
    forged = f"{head}.{body}.{sig}"
    with pytest.raises(cognito.TokenError):
        cognito.verify(forged)


def test_unsigned_token_is_refused():
    token = jwt.encode(_claims(), None, algorithm="none")
    with pytest.raises(cognito.TokenError):
        cognito.verify(token)


def test_wrong_audience_or_expired_is_refused():
    with pytest.raises(cognito.TokenError):
        cognito.verify(jwt.encode(_claims(aud="someone-else"), PRIVATE, algorithm="RS256"))
    with pytest.raises(cognito.TokenError):
        cognito.verify(jwt.encode(_claims(exp=int(time.time()) - 5), PRIVATE, algorithm="RS256"))
