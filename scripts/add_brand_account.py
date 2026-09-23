"""
Onboard a brand/campus IG channel into the brand_accounts registry — the
one consistent way to add accounts and their access tokens. No .env edit,
no deploy: the nightly jobs pick the account up from the DB on their next run.

Requires migration 017 (brand_accounts) to be applied.

Typical flows (venv active, with a filled .env):

  # Account in the same Meta Business portfolio (shares the @niltv token grant):
  python -m scripts.add_brand_account --shared-token --user-id 178414... \
      --name truebluetv --campus duke --network

  # Account with its own token (Facebook Login "EAA..." or Instagram Login "IG..."):
  python -m scripts.add_brand_account --token EAAxxxx --campus duke --network

  # See everything the pipeline will pull tonight (env + DB merged):
  python -m scripts.add_brand_account --list

  # Copy the current .env-defined accounts into the DB registry (one-time):
  python -m scripts.add_brand_account --import-env

  # Pause / resume an account without deleting its data:
  python -m scripts.add_brand_account --deactivate truebluetv
  python -m scripts.add_brand_account --activate truebluetv

What --token does before storing anything:
  1. Detects the API host by token prefix ("IG..." -> graph.instagram.com,
     otherwise graph.facebook.com).
  2. Validates the token by reading the account's profile (and for FB tokens
     without --user-id, discovers the linked IG business account via /me/accounts).
  3. FB tokens: exchanges for a fresh 60-day long-lived token when
     BRAND_IG_APP_ID/SECRET are configured (safe on already-long-lived input).
  4. Stores the account row; the monthly refresh cron keeps the token fresh
     from then on.

Use --network for channels whose athlete collab posts should flow into
niltv_network_posts (the collaborative_media edge; FB-login tokens only).
"""

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone

import httpx

from backend.config import get_settings
from backend.database import SessionLocal
from backend.models import BrandAccount

FB_BASE = "https://graph.facebook.com/v24.0"
IG_BASE = "https://graph.instagram.com/v24.0"

TOKEN_TTL = timedelta(days=60)


def _err(data: dict, resp: httpx.Response) -> str:
    return data.get("error", {}).get("message", resp.text[:200])


def _get(url: str, params: dict) -> dict:
    resp = httpx.get(url, params=params, timeout=30.0)
    data = resp.json()
    if resp.status_code >= 400 or "error" in data:
        raise SystemExit(f"Graph API error: {_err(data, resp)}")
    return data


def env_name(username: str) -> str:
    name = re.sub(r"[^a-z0-9_]", "", username.lower())
    return name or "account"


def discover_fb_account(token: str, user_id: str | None, name: str | None) -> tuple[str, str]:
    """Resolve (ig_user_id, username) for a Facebook-Login token."""
    if user_id:
        data = _get(f"{FB_BASE}/{user_id}", {"fields": "username", "access_token": token})
        return user_id, data.get("username", "")

    # Page tokens (the per-campus-channel setup): /me IS the Page, and the IG
    # account is linked directly on it. User tokens error on this field
    # ("nonexisting field") and fall through to /me/accounts enumeration.
    resp = httpx.get(f"{FB_BASE}/me", params={
        "fields": "name,instagram_business_account{id,username}",
        "access_token": token,
    }, timeout=30.0)
    data = resp.json()
    if resp.status_code < 400 and "error" not in data:
        ig = data.get("instagram_business_account")
        if not ig:
            raise SystemExit(
                f"Page '{data.get('name')}' has no linked Instagram business account — "
                "link the IG account to the Page in Meta Business Suite, then rerun."
            )
        return ig["id"], ig.get("username", "")

    candidates: list[tuple[str, str]] = []
    url, params = f"{FB_BASE}/me/accounts", {
        "fields": "name,instagram_business_account{id,username}",
        "limit": 50,
        "access_token": token,
    }
    while url:
        data = _get(url, params or {})
        for page in data.get("data", []):
            ig = page.get("instagram_business_account")
            if ig:
                candidates.append((ig["id"], ig.get("username", "")))
        url, params = data.get("paging", {}).get("next"), None

    if not candidates:
        raise SystemExit("Token sees no Pages with a linked IG business account. Pass --user-id.")
    if name:
        matches = [c for c in candidates if env_name(c[1]) == name.lower()]
        if len(matches) == 1:
            return matches[0]
    if len(candidates) == 1:
        return candidates[0]
    print("Token sees multiple IG accounts — rerun with --user-id <id>:")
    for ig_id, username in candidates:
        print(f"  @{username}  (id {ig_id})")
    raise SystemExit(1)


def exchange_fb_token(token: str, settings) -> tuple[str, datetime | None]:
    """Exchange for a fresh 60-day long-lived token (no-op without app creds)."""
    if not settings.brand_ig_app_id or not settings.brand_ig_app_secret:
        print("BRAND_IG_APP_ID/SECRET not set — storing token as-is (assumed long-lived).")
        return token, datetime.now(tz=timezone.utc) + TOKEN_TTL
    data = _get(f"{FB_BASE}/oauth/access_token", {
        "grant_type": "fb_exchange_token",
        "client_id": settings.brand_ig_app_id,
        "client_secret": settings.brand_ig_app_secret,
        "fb_exchange_token": token,
    })
    expires_in = data.get("expires_in") or 0
    expires_at = datetime.now(tz=timezone.utc) + (
        timedelta(seconds=expires_in) if expires_in else TOKEN_TTL
    )
    return data["access_token"], expires_at


def upsert(db, *, account: str, username: str, ig_user_id: str, token: str | None,
           api: str, args) -> None:
    now = datetime.now(tz=timezone.utc)
    row = db.query(BrandAccount).filter(BrandAccount.account == account).first()
    created = row is None
    if created:
        row = BrandAccount(account=account, created_at=now)
        db.add(row)
    row.username = username or row.username
    row.ig_user_id = ig_user_id
    row.access_token = token
    row.api = api
    row.post_limit = args.limit
    row.campus = args.campus or row.campus
    row.network_pull = args.network
    row.active = True
    row.notes = args.notes or row.notes
    if token:
        row.token_refreshed_at = now
        row.token_expires_at = getattr(args, "_token_expires_at", None) or now + TOKEN_TTL
    row.updated_at = now
    db.commit()

    verb = "Registered" if created else "Updated"
    print(f"\n{verb} '{account}' (@{username or '?'}) — api={api}, "
          f"campus={row.campus or '-'}, network_pull={row.network_pull}, limit={row.post_limit}")
    print("Nightly pull picks it up at 5:00 UTC (posts) / 5:30 UTC (network)."
          "\nBackfill full post history now (optional):"
          f"\n  python -m backend.jobs.backfill_brand_ig {account}")


def cmd_list(db) -> None:
    from backend.brand_registry import get_brand_targets
    targets = get_brand_targets(db)
    if not targets:
        print("No accounts configured.")
        return
    now = datetime.now(tz=timezone.utc)
    print(f"{'account':<16} {'source':<7} {'api':<4} {'campus':<10} {'network':<8} {'limit':<6} token expiry")
    for t in targets:
        source = "db" if t["db_id"] is not None else "env"
        expiry = "-"
        if t["db_id"] is not None:
            row = db.get(BrandAccount, t["db_id"])
            if row and row.token_expires_at:
                days = (row.token_expires_at - now).days
                expiry = f"{row.token_expires_at:%Y-%m-%d} ({days}d)" + (" ⚠ EXPIRING" if days < 10 else "")
            elif not t["own_token"]:
                expiry = "(shared portfolio token)"
        print(f"{t['account']:<16} {source:<7} {t['api']:<4} {str(t.get('campus') or '-'):<10} "
              f"{str(t['network_pull']):<8} {t['limit']:<6} {expiry}")


def cmd_import_env(db, settings) -> None:
    imported = 0
    for t in settings.brand_ig_targets():
        if db.query(BrandAccount).filter(BrandAccount.account == t["account"]).first():
            print(f"'{t['account']}' already in DB — skipped.")
            continue
        own = t["token_env_var"] != "BRAND_IG_ACCESS_TOKEN" or t["account"] == "niltv"
        now = datetime.now(tz=timezone.utc)
        db.add(BrandAccount(
            account=t["account"],
            ig_user_id=t["ig_user_id"],
            access_token=t["access_token"] if own else None,
            api=t["api"],
            post_limit=t["limit"],
            network_pull=t["account"] == "niltv",
            active=True,
            token_refreshed_at=now if own else None,
            token_expires_at=(now + TOKEN_TTL) if own else None,
            notes=f"imported from .env ({t['token_env_var']})",
            created_at=now,
        ))
        imported += 1
        print(f"Imported '{t['account']}' (api={t['api']}, own_token={own}).")
    db.commit()
    print(f"\n{imported} account(s) imported. The DB rows now override their .env entries.")


def set_active(db, account: str, active: bool) -> None:
    row = db.query(BrandAccount).filter(BrandAccount.account == account).first()
    if not row:
        raise SystemExit(f"No brand_accounts row named '{account}'.")
    row.active = active
    row.updated_at = datetime.now(tz=timezone.utc)
    db.commit()
    print(f"'{account}' {'activated' if active else 'deactivated'}.")


def set_campus(db, account: str, campus: str | None) -> None:
    """Set (or clear) the campus grouping on an existing row — feeds
    ambassador campus inference (collab_accounts -> brand_accounts.campus)."""
    row = db.query(BrandAccount).filter(BrandAccount.account == account).first()
    if not row:
        raise SystemExit(
            f"No brand_accounts row named '{account}'. "
            "(env-defined accounts need --import-env first)"
        )
    row.campus = (campus or "").strip().lower() or None
    row.updated_at = datetime.now(tz=timezone.utc)
    db.commit()
    print(f"'{account}' campus -> {row.campus or '(cleared)'}. "
          "Ambassador campus inference picks it up on the next 05:30 UTC run.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--token", help="account's own access token (EAA... or IG...)")
    ap.add_argument("--shared-token", action="store_true",
                    help="account is covered by the BRAND_IG_ACCESS_TOKEN portfolio grant")
    ap.add_argument("--user-id", help="numeric IG user id (required with --shared-token)")
    ap.add_argument("--name", help="account name / DB discriminator (default: derived from IG username)")
    ap.add_argument("--campus", help="school/node grouping, e.g. duke")
    ap.add_argument("--limit", type=int, default=25, help="posts fetched per nightly run (default 25)")
    ap.add_argument("--network", action="store_true",
                    help="also pull this account's collab/network posts (FB tokens only)")
    ap.add_argument("--notes", help="free-text note stored on the row")
    ap.add_argument("--list", action="store_true", help="print the merged registry and token expiry")
    ap.add_argument("--import-env", action="store_true", help="copy .env-defined accounts into the DB")
    ap.add_argument("--deactivate", metavar="ACCOUNT", help="pause an account (keeps its data)")
    ap.add_argument("--activate", metavar="ACCOUNT", help="resume a paused account")
    ap.add_argument("--set-campus", metavar="ACCOUNT",
                    help="set campus on an existing row (pair with --campus VALUE; omit --campus to clear)")
    args = ap.parse_args()

    settings = get_settings()
    db = SessionLocal()
    try:
        if args.list:
            return cmd_list(db)
        if args.import_env:
            return cmd_import_env(db, settings)
        if args.deactivate:
            return set_active(db, args.deactivate, False)
        if args.activate:
            return set_active(db, args.activate, True)
        if args.set_campus:
            return set_campus(db, args.set_campus, args.campus)

        if args.shared_token:
            token_to_probe = settings.brand_ig_access_token
            if not token_to_probe:
                raise SystemExit("--shared-token requires BRAND_IG_ACCESS_TOKEN in .env.")
            if not args.user_id:
                raise SystemExit("--shared-token requires --user-id "
                                 "(discover ids with: python -m scripts.list_ig_accounts).")
            ig_user_id, username = discover_fb_account(token_to_probe, args.user_id, args.name)
            upsert(db, account=args.name or env_name(username), username=username,
                   ig_user_id=ig_user_id, token=None, api="fb", args=args)
            return

        if not args.token:
            ap.print_help()
            raise SystemExit("\nPass --token, --shared-token, or one of --list/--import-env/--activate/--deactivate.")

        if args.token.startswith("IG"):
            # Instagram-Login token: host-locked to graph.instagram.com, addresses
            # the account as "me". These come out of the app dashboard generator
            # already long-lived; the monthly cron keeps them fresh.
            data = _get(f"{IG_BASE}/me", {"fields": "username", "access_token": args.token})
            username = data.get("username", "")
            if args.network:
                print("Note: --network ignored — the collaborative_media edge needs a "
                      "Facebook-Login token; Instagram-Login tokens can't reach it.")
                args.network = False
            upsert(db, account=args.name or env_name(username), username=username,
                   ig_user_id="me", token=args.token, api="ig", args=args)
        else:
            ig_user_id, username = discover_fb_account(args.token, args.user_id, args.name)
            token, expires_at = exchange_fb_token(args.token, settings)
            args._token_expires_at = expires_at
            upsert(db, account=args.name or env_name(username), username=username,
                   ig_user_id=ig_user_id, token=token, api="fb", args=args)
    finally:
        db.close()


if __name__ == "__main__":
    main()
