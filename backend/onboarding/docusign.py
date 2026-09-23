"""DocuSign eSignature client for the onboarding pipeline.

Auth is the JWT grant: an integration key + RSA private key, acting as one
consented API user. Envelopes are created from the ambassador agreement
template with the signer's name/email and the school/sport/handle custom
fields prefilled from the application row. The Connect webhook
(``verify_connect_signature``) tells us when the envelope completes.

Plain REST over httpx; PyJWT is the only addition (RS256 assertion).
Every failure raises ``DocuSignError`` so the pipeline can record it on the
application timeline instead of 500-ing the request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from backend.config import get_settings


class DocuSignError(RuntimeError):
    pass


def is_configured() -> bool:
    s = get_settings()
    return bool(
        s.docusign_integration_key
        and s.docusign_user_id
        and s.docusign_account_id
        and s.docusign_private_key_path
        and s.docusign_template_id
    )


# -- Auth -------------------------------------------------------------------

_token_cache: dict[str, Any] = {"token": None, "expires": 0.0}


def _read_private_key() -> str:
    path = get_settings().docusign_private_key_path
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError as e:
        raise DocuSignError(f"cannot read DocuSign private key at {path}: {e}") from e


def consent_url() -> str:
    """One-time admin consent URL (open once in a browser as the API user)."""
    s = get_settings()
    return (
        f"https://{s.docusign_oauth_host}/oauth/auth?response_type=code"
        f"&scope=signature%20impersonation&client_id={s.docusign_integration_key}"
        f"&redirect_uri=https://{s.docusign_oauth_host}/me"
    )


def access_token() -> str:
    """JWT-grant access token, cached until a minute before expiry."""
    now = time.time()
    if _token_cache["token"] and _token_cache["expires"] - 60 > now:
        return _token_cache["token"]
    try:
        import jwt  # PyJWT
    except ImportError as e:  # pragma: no cover
        raise DocuSignError("PyJWT is not installed") from e
    s = get_settings()
    claims = {
        "iss": s.docusign_integration_key,
        "sub": s.docusign_user_id,
        "aud": s.docusign_oauth_host,
        "iat": int(now),
        "exp": int(now) + 3600,
        "scope": "signature impersonation",
    }
    assertion = jwt.encode(claims, _read_private_key(), algorithm="RS256")
    try:
        r = httpx.post(
            f"https://{s.docusign_oauth_host}/oauth/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
            timeout=20,
        )
    except httpx.HTTPError as e:
        raise DocuSignError(f"DocuSign token request failed: {e}") from e
    if r.status_code != 200:
        detail = r.text[:300]
        if "consent_required" in detail:
            detail += f" -> open {consent_url()} once as the API user"
        raise DocuSignError(f"DocuSign token HTTP {r.status_code}: {detail}")
    body = r.json()
    _token_cache["token"] = body["access_token"]
    _token_cache["expires"] = now + int(body.get("expires_in", 3600))
    return _token_cache["token"]


_base_uri_cache: dict[str, str] = {}


def resolve_base_uri() -> str:
    """The account's REST base URI (e.g. https://na4.docusign.net).

    Uses DOCUSIGN_BASE_URI when set. When empty, asks /oauth/userinfo which
    shard hosts DOCUSIGN_ACCOUNT_ID and caches the answer, so nobody has to
    find the value on the Apps and Keys page."""
    s = get_settings()
    if s.docusign_base_uri:
        return s.docusign_base_uri.rstrip("/")
    if "uri" in _base_uri_cache:
        return _base_uri_cache["uri"]
    try:
        r = httpx.get(
            f"https://{s.docusign_oauth_host}/oauth/userinfo", timeout=20,
            headers={"Authorization": f"Bearer {access_token()}"},
        )
    except httpx.HTTPError as e:
        raise DocuSignError(f"DocuSign userinfo failed: {e}") from e
    if r.status_code != 200:
        raise DocuSignError(f"DocuSign userinfo HTTP {r.status_code}: {r.text[:200]}")
    accounts = r.json().get("accounts") or []
    ids = ", ".join(a.get("account_id", "?") for a in accounts) or "none"
    want = s.docusign_account_id.lower()
    match = next((a for a in accounts if (a.get("account_id") or "").lower() == want), None)
    if match is None or not match.get("base_uri"):
        raise DocuSignError(
            f"DOCUSIGN_ACCOUNT_ID {s.docusign_account_id} is not one of this user's accounts ({ids})"
        )
    _base_uri_cache["uri"] = match["base_uri"].rstrip("/")
    return _base_uri_cache["uri"]


def _api(method: str, path: str, json: Optional[dict] = None) -> dict:
    s = get_settings()
    url = f"{resolve_base_uri()}/restapi/v2.1/accounts/{s.docusign_account_id}{path}"
    try:
        r = httpx.request(
            method, url, json=json, timeout=30,
            headers={"Authorization": f"Bearer {access_token()}"},
        )
    except httpx.HTTPError as e:
        raise DocuSignError(f"DocuSign {method} {path} failed: {e}") from e
    if r.status_code >= 300:
        raise DocuSignError(f"DocuSign {method} {path} HTTP {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {}


# -- Envelopes --------------------------------------------------------------

@dataclass
class EnvelopeFields:
    email: str
    name: str
    school: str = ""
    sport: str = ""
    handle: str = ""
    application_id: int = 0


def _greeting_name(name: Optional[str]) -> str:
    first = (name or "").strip().split(" ")[0]
    if not first:
        return "there"
    return first[:1].upper() + first[1:]


def create_envelope(fields: EnvelopeFields) -> str:
    """Create and send an envelope from the agreement template. Returns the
    envelope id. The template's signer role must match
    ``docusign_template_role``. school/sport/handle go in as envelope custom
    fields (visible in the DocuSign admin list) and as text tabs of the same
    label when the template defines them."""
    s = get_settings()
    text_tabs = [
        {"tabLabel": "school", "value": fields.school or ""},
        {"tabLabel": "sport", "value": fields.sport or ""},
        {"tabLabel": "handle", "value": fields.handle or ""},
    ]
    payload = {
        "templateId": s.docusign_template_id,
        "status": "sent",
        "emailSubject": "Your NIL TV Ambassador Agreement",
        "emailBlurb": (
            f"Hi {_greeting_name(fields.name)}, welcome to NIL TV. "
            "Please review and sign your Ambassador Agreement. Once it is signed we send your "
            "payout setup link. Questions: https://niltv.com/contact/"
        ),
        "customFields": {
            "textCustomFields": [
                {"name": "school", "value": fields.school or "", "show": "true"},
                {"name": "sport", "value": fields.sport or "", "show": "true"},
                {"name": "handle", "value": fields.handle or "", "show": "true"},
                {"name": "application_id", "value": str(fields.application_id), "show": "false"},
            ]
        },
        "templateRoles": [{
            "roleName": s.docusign_template_role,
            "name": fields.name,
            "email": fields.email,
            "tabs": {"textTabs": text_tabs},
        }],
    }
    if s.docusign_brand_id:
        payload["brandId"] = s.docusign_brand_id
    if s.docusign_reply_email:
        payload["emailSettings"] = {
            "replyEmailAddressOverride": s.docusign_reply_email,
            "replyEmailNameOverride": s.docusign_reply_name or "NIL TV",
        }
    body = _api("POST", "/envelopes", payload)
    env_id = body.get("envelopeId")
    if not env_id:
        raise DocuSignError(f"no envelopeId in response: {body}")
    return env_id


def envelope_status(envelope_id: str) -> dict:
    """{'status': sent|delivered|completed|declined|voided, 'completed_at': iso|None, ...}"""
    body = _api("GET", f"/envelopes/{envelope_id}")
    return {
        "status": (body.get("status") or "").lower(),
        "completed_at": body.get("completedDateTime"),
        "sent_at": body.get("sentDateTime"),
        "declined_at": body.get("declinedDateTime"),
        "voided_reason": body.get("voidedReason"),
    }


def void_envelope(envelope_id: str, reason: str) -> None:
    """Void an envelope that is still out for signature (declined applicant)."""
    _api("PUT", f"/envelopes/{envelope_id}", {"status": "voided", "voidedReason": reason[:200] or "Voided by NIL TV"})


def resend(envelope_id: str) -> None:
    """Re-send the signing notification to the recipients."""
    _api("PUT", f"/envelopes/{envelope_id}?resend_envelope=true", {})


# -- Connect webhook --------------------------------------------------------

def verify_connect_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """DocuSign Connect HMAC: base64(HMAC-SHA256(secret, raw body)) in the
    X-DocuSign-Signature-1 header (-2 etc. when several keys are active)."""
    secret = get_settings().docusign_connect_secret
    if not secret or not signature_header:
        return False
    expected = base64.b64encode(
        hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature_header.strip())


def parse_connect_event(body: dict) -> dict:
    """Normalize a Connect JSON (SIM) event to a flat dict:
    event, envelope_id, status, completed_at, signer_email, custom_fields."""
    data = body.get("data") or {}
    summary = data.get("envelopeSummary") or {}
    event = (body.get("event") or "").lower()
    status = (summary.get("status") or event.replace("envelope-", "")).lower()
    signer_email = None
    for r in ((summary.get("recipients") or {}).get("signers") or []):
        if r.get("email"):
            signer_email = r["email"].strip().lower()
            break
    custom: dict[str, str] = {}
    for f in ((summary.get("customFields") or {}).get("textCustomFields") or []):
        if f.get("name"):
            custom[f["name"]] = f.get("value") or ""
    return {
        "event": event,
        "envelope_id": data.get("envelopeId") or summary.get("envelopeId"),
        "status": status,
        "completed_at": summary.get("completedDateTime"),
        "signer_email": signer_email,
        "custom_fields": custom,
    }
