"""
Cron job: Refresh the brand Instagram long-lived access tokens.

Run:
    scripts/run_job.sh backend.jobs.refresh_brand_ig_token

Runs on the 2nd of every month. Tokens expire after 60 days, so this
ensures every brand token is always fresh (offset from athlete refresh on
the 1st). Covers the merged registry (brand_accounts table + legacy .env
entries), refreshing each distinct token once — accounts sharing a token
share the refresh.

On success: DB-registered tokens are written back to their brand_accounts
row (with token_refreshed_at / token_expires_at stamped); env-registered
tokens update their var in the .env file on the server. Failures raise
through run_job, which sends the SNS email alert.
"""

import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.brand_registry import get_brand_targets
from backend.database import SessionLocal
from backend.jobs.base import run_job
from backend.models import BrandAccount
from backend.sources.brand_ig import refresh_brand_token

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

ENV_FILE = Path(__file__).parent.parent.parent / ".env"

DEFAULT_TTL = timedelta(days=60)


def _save_token(env_var: str, new_token: str) -> None:
    if not ENV_FILE.exists():
        # Never log the token itself: job output lands in files and CloudWatch.
        logger.error(
            f".env not found at {ENV_FILE}. {env_var} NOT saved; re-run this job where the "
            f".env lives (new token ends with ...{new_token[-4:]})."
        )
        return

    content = ENV_FILE.read_text(encoding="utf-8")
    pattern = rf"^{env_var}=.*$"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, f"{env_var}={new_token}", content, flags=re.MULTILINE)
    else:
        content = content.rstrip("\n") + f"\n{env_var}={new_token}\n"
    ENV_FILE.write_text(content, encoding="utf-8")
    logger.info(f"Updated {env_var} in {ENV_FILE}")


def _refresh_all(db) -> int:
    # Group targets by token value so a shared (portfolio) token is exchanged
    # exactly once, then the result is written to every place that stores it:
    # brand_accounts rows with their own copy, and/or an .env var.
    groups: dict[str, dict] = {}  # token -> {"env_vars": set, "db_ids": set, "label": str}
    for t in get_brand_targets(db):
        tok = t["access_token"]
        if not tok:
            continue
        g = groups.setdefault(tok, {"env_vars": set(), "db_ids": set(), "label": t["account"]})
        if t["db_id"] is not None and t["own_token"]:
            g["db_ids"].add(t["db_id"])
        elif t["db_id"] is None and t["token_env_var"]:
            g["env_vars"].add(t["token_env_var"])
        # DB rows without their own token ride on the BRAND_IG_ACCESS_TOKEN
        # grant — that token is env-held, so its refresh lands in .env via the
        # legacy niltv env target in the same group.

    if not groups:
        raise RuntimeError("No brand tokens configured — nothing to refresh.")

    now = datetime.now(tz=timezone.utc)
    refreshed = 0
    failures: list[str] = []
    for token, g in groups.items():
        label = ", ".join(sorted(g["env_vars"]) or [g["label"]])
        logger.info(f"Refreshing long-lived token for {label}...")
        try:
            result = refresh_brand_token(token)
        except Exception as e:
            failures.append(f"{label}: refresh request failed: {e}")
            continue

        new_token = result.get("access_token")
        expires_in = result.get("expires_in") or 0
        if not new_token:
            failures.append(f"{label}: no access_token in response: {result}")
            continue

        expires_at = now + (timedelta(seconds=expires_in) if expires_in else DEFAULT_TTL)
        logger.info(f"[{label}] Token refreshed. Expires {expires_at:%Y-%m-%d}.")

        for env_var in g["env_vars"]:
            _save_token(env_var, new_token)
        for db_id in g["db_ids"]:
            row = db.get(BrandAccount, db_id)
            if row:
                row.access_token = new_token
                row.token_refreshed_at = now
                row.token_expires_at = expires_at
                row.updated_at = now
                logger.info(f"Updated brand_accounts row '{row.account}'")
        db.commit()
        refreshed += 1

    if failures:
        raise RuntimeError("Token refresh failures:\n" + "\n".join(failures))
    return refreshed


def main():
    db = SessionLocal()
    try:
        run_job("refresh_brand_ig_token", db, _refresh_all, db)
    except Exception:
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
