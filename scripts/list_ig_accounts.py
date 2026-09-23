"""
Onboarding helper: enumerate every Instagram Business account the brand token
can access, and print ready-to-paste .env lines for BRAND_IG_EXTRA_ACCOUNTS.

After granting the Meta app access to new Pages/IG accounts in Business Suite
(and regenerating the token with those assets checked), run this to discover
their numeric IG user ids and confirm the token can actually read them.

Run with a filled .env and the venv active:

    python -m scripts.list_ig_accounts

Read-only — makes GET calls against the Graph API, writes nothing.
"""

import re

import httpx

from backend.config import get_settings

BASE = "https://graph.facebook.com/v24.0"

settings = get_settings()
TOKEN = settings.brand_ig_access_token

# Accounts the pipeline already tracks (skip them in the suggested .env block).
KNOWN_IG_IDS = {settings.brand_ig_user_id, settings.nilstar_ig_user_id}


def _err(r: httpx.Response) -> str:
    try:
        return r.json().get("error", {}).get("message", r.text[:160])
    except Exception:
        return r.text[:160]


def list_pages() -> list[dict]:
    """All Pages the token can see, with their linked IG business account."""
    pages: list[dict] = []
    url = f"{BASE}/me/accounts"
    params = {
        "fields": "name,instagram_business_account{id,username,followers_count}",
        "limit": 50,
        "access_token": TOKEN,
    }
    while url:
        r = httpx.get(url, params=params, timeout=30.0)
        if r.status_code >= 400:
            print(f"  /me/accounts failed: {_err(r)}")
            break
        data = r.json()
        pages.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = None
    return pages


def probe(ig_id: str) -> str | None:
    """Confirm the token can read the IG account directly (what the nightly
    job does). Returns an error message, or None on success."""
    r = httpx.get(
        f"{BASE}/{ig_id}",
        params={"fields": "username,media_count", "access_token": TOKEN},
        timeout=30.0,
    )
    if r.status_code >= 400 or "error" in r.json():
        return _err(r)
    return None


def env_name(username: str) -> str:
    """IG username -> env-safe account name (also the DB discriminator)."""
    name = re.sub(r"[^a-z0-9_]", "", username.lower())
    return name or "account"


def main():
    if not TOKEN:
        print("BRAND_IG_ACCESS_TOKEN not set in .env — aborting.")
        return

    pages = list_pages()
    print(f"\nToken sees {len(pages)} Page(s):\n")

    new_accounts: list[tuple[str, str]] = []  # (name, ig_user_id)
    for page in pages:
        ig = page.get("instagram_business_account")
        if not ig:
            print(f"  {page.get('name')}: no linked IG business account")
            continue
        ig_id, username = ig["id"], ig.get("username", "?")
        err = probe(ig_id)
        status = f"ERROR: {err}" if err else f"OK ({ig.get('followers_count', '?')} followers)"
        tracked = " [already tracked]" if ig_id in KNOWN_IG_IDS else ""
        print(f"  {page.get('name')}: @{username} (id {ig_id}) — {status}{tracked}")
        if not err and ig_id not in KNOWN_IG_IDS:
            new_accounts.append((env_name(username), ig_id))

    if not new_accounts:
        print("\nNo new readable accounts found beyond the ones already tracked.")
        return

    print("\nPaste into .env (token falls back to BRAND_IG_ACCESS_TOKEN):\n")
    print(f"BRAND_IG_EXTRA_ACCOUNTS={','.join(n for n, _ in new_accounts)}")
    for name, ig_id in new_accounts:
        print(f"{name.upper()}_IG_USER_ID={ig_id}")


if __name__ == "__main__":
    main()
