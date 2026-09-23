"""Stripe Connect (Express) client for the onboarding pipeline.

Plain REST over httpx (no stripe SDK). Creates the Express account once the
agreement is signed, reads requirements/payouts state, and verifies the
``account.updated`` webhook signature. The permanent payout link uses the
same HMAC token scheme as the payouts-start Lambda
(``base64url("<acct>.<hmac24>")`` under LINK_SIGNING_SECRET), so the URL we
email never expires and resolves to a fresh Stripe link on each click.

Accounts are created with the Accounts v2 API (``POST /v2/core/accounts``,
recipient configuration, Express dashboard): live mode no longer lets a new
platform create v1 accounts. Everything after creation stays on v1, which
Stripe supports for v2 account ids: ``GET /v1/accounts/{id}`` returns the
v1-shaped object the dashboard reads, the manual payout schedule is a v1
update, account links and Express login links (the payout Lambda) take the
id as-is, and ``account.updated`` still fires on the connected-accounts
webhook scope. The restricted key needs Connect > Accounts: Write plus
Accounts v2: Write.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any, Optional

import httpx

from backend.config import get_settings

SIG_LEN = 24  # keep in sync with the payouts-start Lambda's token check
V2_API_VERSION = "2026-08-26.dahlia"  # Stripe-Version required by the /v2 endpoints


class StripeError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(get_settings().stripe_secret_key)


def _api(method: str, path: str, data: Optional[dict] = None, json: Optional[dict] = None) -> dict:
    """v1 endpoints take form-encoded ``data``; /v2 endpoints take a JSON body
    and the pinned Stripe-Version header."""
    s = get_settings()
    if not s.stripe_secret_key:
        raise StripeError("STRIPE_SECRET_KEY is not configured")
    headers = {"Authorization": f"Bearer {s.stripe_secret_key}"}
    if path.startswith("/v2/"):
        headers["Stripe-Version"] = V2_API_VERSION
    try:
        r = httpx.request(
            method, "https://api.stripe.com" + path, data=data, json=json, timeout=30,
            headers=headers,
        )
    except httpx.HTTPError as e:
        raise StripeError(f"Stripe {method} {path} failed: {e}") from e
    if r.status_code >= 300:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            msg = r.text[:200]
        raise StripeError(f"Stripe {method} {path} HTTP {r.status_code}: {msg}")
    return r.json()


def _flatten(prefix: str, obj: Any, out: dict) -> dict:
    """Stripe form encoding: metadata[school]=..., capabilities[transfers][requested]=true"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(f"{prefix}[{k}]" if prefix else k, v, out)
    elif isinstance(obj, bool):
        out[prefix] = "true" if obj else "false"
    elif obj is not None:
        out[prefix] = str(obj)
    return out


def create_express_account(email: str, metadata: dict[str, str], name: str = "") -> dict:
    """Express dashboard, US individual, recipient configuration with the
    stripe_transfers capability (v1 ``transfers``), manual payout schedule
    so Stripe never pays out on its own. Metadata (contract_signed,
    envelope_id, program, school, sport, handle, application_id) keeps the
    Connect account list usable as a roster.

    Returns the v1-shaped account (payouts_enabled, requirements) so callers
    read it exactly like a webhook or ``get_account`` payload."""
    created = _api("POST", "/v2/core/accounts", json={
        "contact_email": email,
        "display_name": name or email,
        "dashboard": "express",
        "identity": {"country": "us", "entity_type": "individual"},
        "configuration": {"recipient": {"capabilities": {
            "stripe_balance": {"stripe_transfers": {"requested": True}},
        }}},
        # Express requires the platform to collect fees and carry losses.
        "defaults": {
            "currency": "usd",
            "locales": ["en-US"],
            "responsibilities": {"fees_collector": "application", "losses_collector": "application"},
        },
        "metadata": {k: v for k, v in metadata.items() if v},
    })
    account_id = created.get("id")
    if not account_id:
        raise StripeError(f"no account id in v2 create response: {created}")
    # Payout schedule is a v1 setting; the update returns the v1 object.
    return _api("POST", f"/v1/accounts/{account_id}",
                _flatten("", {"settings": {"payouts": {"schedule": {"interval": "manual"}}}}, {}))


def get_account(account_id: str) -> dict:
    return _api("GET", f"/v1/accounts/{account_id}")


def account_state(account: dict) -> dict:
    """Condensed view of an account object for the dashboard row."""
    req = account.get("requirements") or {}
    due = list(req.get("currently_due") or [])
    past_due = list(req.get("past_due") or [])
    return {
        "payouts_enabled": bool(account.get("payouts_enabled")),
        "charges_enabled": bool(account.get("charges_enabled")),
        "details_submitted": bool(account.get("details_submitted")),
        "currently_due": due,
        "past_due": past_due,
        "eventually_due": list(req.get("eventually_due") or []),
        "disabled_reason": req.get("disabled_reason"),
        "complete": bool(account.get("payouts_enabled")) and not due and not past_due,
    }


# -- Permanent payout link --------------------------------------------------

def payout_token(account_id: str) -> str:
    secret = get_settings().link_signing_secret
    if not secret:
        raise StripeError("LINK_SIGNING_SECRET is not configured")
    sig = hmac.new(secret.encode(), account_id.encode(), hashlib.sha256).hexdigest()[:SIG_LEN]
    return base64.urlsafe_b64encode(f"{account_id}.{sig}".encode()).decode().rstrip("=")


def payout_link(account_id: str) -> str:
    base = get_settings().site_base.rstrip("/")
    return f"{base}/payouts/start/?t={payout_token(account_id)}"


# -- Webhook ----------------------------------------------------------------

def verify_webhook_signature(
    raw_body: bytes,
    sig_header: Optional[str],
    tolerance: int = 300,
    now: Optional[float] = None,
) -> bool:
    """Stripe-Signature: t=<ts>,v1=<hex>[,v1=<hex>...];
    v1 = HMAC-SHA256(secret, f"{t}.{body}")."""
    secret = get_settings().stripe_webhook_secret
    if not secret or not sig_header:
        return False
    parts: dict[str, list[str]] = {}
    for item in sig_header.split(","):
        if "=" in item:
            k, v = item.strip().split("=", 1)
            parts.setdefault(k, []).append(v)
    ts = (parts.get("t") or [None])[0]
    sigs = parts.get("v1") or []
    if not ts or not sigs:
        return False
    try:
        ts_int = int(ts)
    except ValueError:
        return False
    if abs((now if now is not None else time.time()) - ts_int) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)
