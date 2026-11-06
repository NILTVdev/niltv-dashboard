"""Checks a Community Star vote passes before it can be queued.

Email normalising (one vote per person, official rule 9), the disposable-domain
list, the MX lookup, and Cloudflare Turnstile. Nothing here touches the
database.
"""

from __future__ import annotations

import logging
import re
import time
from functools import lru_cache
from pathlib import Path

import dns.exception
import dns.resolver
import httpx

log = logging.getLogger(__name__)

_DISPOSABLE_PATH = Path(__file__).resolve().parent.parent / "data" / "disposable_email_domains.txt"
_EMAIL = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}$")
_GMAIL = ("gmail.com", "googlemail.com")
_DNS_TIMEOUT = 2.0
_MX_CACHE_SECONDS = 3600.0
_mx_cache: dict[str, tuple[float, bool]] = {}
_TURNSTILE_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class TurnstileUnavailable(RuntimeError):
    """Cloudflare could not answer. The vote is refused, never let through."""


def clean_email(value: object) -> str:
    """The address, lowercased and trimmed, or '' when it is not one."""
    email = value.strip().lower() if isinstance(value, str) else ""
    if not email or len(email) > 200 or not _EMAIL.match(email):
        return ""
    return email if normalize_email(email).partition("@")[0] else ""


def normalize_email(email: str) -> str:
    """The key behind one vote per person: lowercase; +tags dropped; for Gmail
    the dots too, and googlemail.com is gmail.com."""
    local, _, domain = email.strip().lower().rpartition("@")
    local = local.split("+", 1)[0]
    if domain in _GMAIL:
        return f"{local.replace('.', '')}@gmail.com"
    return f"{local}@{domain}"


@lru_cache(maxsize=1)
def disposable_domains() -> frozenset[str]:
    lines = _DISPOSABLE_PATH.read_text(encoding="utf-8").splitlines()
    return frozenset(s for s in (line.strip().lower() for line in lines) if s and not s.startswith("#"))


def is_disposable(domain: str) -> bool:
    """The domain or any parent of it is on the list."""
    listed = disposable_domains()
    parts = domain.lower().split(".")
    return any(".".join(parts[i:]) in listed for i in range(len(parts) - 1))


def _lookup(resolver: dns.resolver.Resolver, domain: str, kind: str) -> list:
    return list(resolver.resolve(domain, kind))


def _resolves_for_mail(domain: str) -> bool:
    """False only on a definite no: the domain does not exist, it publishes a
    null MX (RFC 7505), or it has no MX and no address. A timeout or a server
    failure passes, so a slow resolver never costs a real voter their vote."""
    resolver = dns.resolver.Resolver()
    resolver.lifetime = _DNS_TIMEOUT
    try:
        records = _lookup(resolver, domain, "MX")
        return not all(str(r.exchange) == "." for r in records)
    except dns.resolver.NXDOMAIN:
        return False
    except dns.resolver.NoAnswer:
        pass
    except dns.exception.DNSException:
        return True
    try:
        return bool(_lookup(resolver, domain, "A"))
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return False
    except dns.exception.DNSException:
        return True


def has_mail_route(domain: str) -> bool:
    now = time.monotonic()
    hit = _mx_cache.get(domain)
    if hit and now - hit[0] < _MX_CACHE_SECONDS:
        return hit[1]
    if len(_mx_cache) > 20000:
        _mx_cache.clear()
    ok = _resolves_for_mail(domain)
    _mx_cache[domain] = (now, ok)
    return ok


def turnstile_ok(secret: str, token: str, ip: str) -> bool:
    """Whether Cloudflare accepts the token. TurnstileUnavailable when it
    cannot be asked."""
    if not token:
        return False
    try:
        res = httpx.post(_TURNSTILE_URL, data={"secret": secret, "response": token, "remoteip": ip}, timeout=5.0)
        res.raise_for_status()
        return res.json().get("success") is True
    except (httpx.HTTPError, ValueError, AttributeError) as e:
        log.warning("turnstile: verify failed: %s", type(e).__name__)
        raise TurnstileUnavailable from e
