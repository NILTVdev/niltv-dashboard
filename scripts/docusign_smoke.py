"""DocuSign smoke test.

Uses the JWT credentials in .env (same ones the API uses) to hit harmless
read endpoints on the demo account. A clean run proves the key, user id,
account id, base URI, private key, and consent are all correct. The default
of 22 calls clears DocuSign's minimum of 20 successful calls for Go-Live.

Run where the private key is available, with the venv active:
    python -m scripts.docusign_smoke            # 22 calls
    python -m scripts.docusign_smoke --calls 5  # quick check

Exit code 0 = every call succeeded.
"""

from __future__ import annotations

import argparse
import sys
import time

from backend.config import get_settings
from backend.onboarding import docusign


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", type=int, default=22, help="how many successful API calls to make")
    args = ap.parse_args()

    s = get_settings()
    print(f"oauth host : {s.docusign_oauth_host}")
    print(f"base uri   : {s.docusign_base_uri or '(auto via userinfo)'}")
    print(f"account id : {s.docusign_account_id}")
    print(f"user id    : {s.docusign_user_id}")
    print(f"client id  : {s.docusign_integration_key}")
    print(f"template   : {s.docusign_template_id or '(none)'}")
    if not docusign.is_configured():
        print("\nDocuSign is not fully configured in .env (see the ops runbook).")
        return 2

    try:
        docusign.access_token()
    except docusign.DocuSignError as e:
        print(f"\nTOKEN FAILED: {e}")
        if "consent" in str(e).lower():
            print(f"\nOpen this once as the API user, then rerun:\n  {docusign.consent_url()}")
        return 1
    print("\ntoken OK")
    try:
        print(f"base uri   : {docusign.resolve_base_uri()} (resolved)")
    except docusign.DocuSignError as e:
        print(f"\nBASE URI FAILED: {e}")
        return 1

    # Read-only endpoints: account info, template list, our template, envelopes list.
    plan = [
        ("GET", "", "account"),
        ("GET", "/templates?count=1", "templates"),
        ("GET", f"/templates/{s.docusign_template_id}", "our template"),
        ("GET", "/envelopes?from_date=2026-01-01T00:00:00Z&count=1", "envelopes"),
        ("GET", "/settings", "settings"),
        ("GET", "/users?count=1", "users"),
    ]
    ok = 0
    failures = 0
    i = 0
    while ok < args.calls and failures == 0:
        method, path, label = plan[i % len(plan)]
        i += 1
        try:
            docusign._api(method, path)  # noqa: SLF001 - intentional low-level call
            ok += 1
            print(f"  {ok:>2}. {label:<14} OK")
        except docusign.DocuSignError as e:
            failures += 1
            print(f"  !! {label}: {e}")
        time.sleep(0.3)

    print(f"\n{ok} successful calls, {failures} failures")
    if failures:
        return 1
    print("Go-Live needs 20+ successful calls in the last 30 days with zero failures.")
    print("Next: demo Apps and Keys -> the key's Actions menu -> Start Go-Live Review")
    print("      (or Dev Console -> app -> Production tab -> Submit for review, when eligible).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
