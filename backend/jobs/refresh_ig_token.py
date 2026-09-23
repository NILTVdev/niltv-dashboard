"""
Cron job: Refresh the Instagram long-lived access token.

Run:
    python -m backend.jobs.refresh_ig_token

Run monthly. Tokens expire after 60 days, so this keeps the token
fresh.

On success: updates IG_ACCESS_TOKEN in the .env file on the server.
"""

import logging
import re
import sys
from pathlib import Path

from backend.sources.instagram import refresh_long_lived_token

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

ENV_FILE = Path(__file__).parent.parent.parent / ".env"


def main():
    logger.info("Refreshing Instagram long-lived access token...")

    try:
        result = refresh_long_lived_token()
    except Exception as e:
        logger.error(f"Token refresh request failed: {e}")
        sys.exit(1)

    new_token = result.get("access_token")
    expires_in = result.get("expires_in", 0)

    if not new_token:
        logger.error(f"No access_token in response: {result}")
        sys.exit(1)

    logger.info(f"Token refreshed. Expires in {expires_in // 86400} days.")

    if not ENV_FILE.exists():
        # Never log the token itself: job output lands in files and CloudWatch.
        logger.error(
            f".env file not found at {ENV_FILE}. Token NOT saved; re-run this job where the "
            f".env lives (new token ends with ...{new_token[-4:]})."
        )
        sys.exit(1)

    content = ENV_FILE.read_text(encoding="utf-8")
    updated = re.sub(r"^IG_ACCESS_TOKEN=.*$", f"IG_ACCESS_TOKEN={new_token}", content, flags=re.MULTILINE)
    ENV_FILE.write_text(updated, encoding="utf-8")
    logger.info(f"Updated IG_ACCESS_TOKEN in {ENV_FILE}")


if __name__ == "__main__":
    main()
