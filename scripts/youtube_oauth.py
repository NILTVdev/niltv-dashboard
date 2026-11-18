#!/usr/bin/env python3
"""
One-time YouTube Analytics consent: prints a refresh token for the server .env.

Run on a laptop, with a browser, by (or next to) the person who owns the
YouTube channel:

    YOUTUBE_OAUTH_CLIENT_ID=... YOUTUBE_OAUTH_CLIENT_SECRET=... python -m scripts.youtube_oauth

(Both can also come from a local .env, or the secret is asked for.)

What happens:
  1. A small web server starts on 127.0.0.1 on a free port.
  2. The browser opens Google's consent screen for two read-only scopes:
     yt-analytics.readonly and youtube.readonly.
  3. The channel owner signs in with the Google account that owns the
     channel (for a Brand Account channel, pick the channel when asked) and
     approves.
  4. Google redirects back to the local server; the script swaps the code for
     tokens and prints the refresh token.

Put the printed value in the server .env as YOUTUBE_OAUTH_REFRESH_TOKEN, next
to the same client id and secret. The nightly run_youtube_analytics job then
connects on its next run.

The OAuth client must be a "Desktop app" client in the Google Cloud project
that has the YouTube Data API v3 and YouTube Analytics API enabled. Desktop
clients accept any loopback port, so nothing has to be registered. While the
consent screen is in "Testing" mode, Google expires refresh tokens after 7
days: publish the app (internal or in production) before handing the token
to the server.

The refresh token is a credential. It is printed once and written nowhere;
do not paste it into chat, tickets or the repository.
"""

import argparse
import base64
import getpass
import hashlib
import http.server
import os
import secrets
import sys
import threading
import urllib.parse
import webbrowser

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]
WAIT_SECONDS = 300


def _from_env_file(name: str) -> str:
    try:
        from dotenv import dotenv_values
    except ImportError:
        return ""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    return (dotenv_values(path).get(name) or "") if os.path.exists(path) else ""


def _setting(name: str) -> str:
    return (os.environ.get(name) or _from_env_file(name)).strip()


def build_auth_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",     # ask for a refresh token
        "prompt": "consent",          # always return one, even on a repeat grant
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })


class _Catcher(http.server.BaseHTTPRequestHandler):
    result: dict = {}
    done = threading.Event()

    def do_GET(self):  # noqa: N802 - http.server API
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" not in query and "error" not in query:
            self.send_response(404)
            self.end_headers()
            return
        type(self).result = {k: v[0] for k, v in query.items()}
        ok = "code" in query
        body = ("Access approved. You can close this tab and go back to the terminal."
                if ok else "Access was not approved. Go back to the terminal for details.")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())
        type(self).done.set()

    def log_message(self, *_):  # keep the code out of the terminal log
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--no-browser", action="store_true",
                        help="print the consent URL instead of opening a browser")
    args = parser.parse_args()

    client_id = _setting("YOUTUBE_OAUTH_CLIENT_ID")
    client_secret = _setting("YOUTUBE_OAUTH_CLIENT_SECRET")
    if not client_id:
        print("Set YOUTUBE_OAUTH_CLIENT_ID (Desktop app OAuth client) and run again.", file=sys.stderr)
        return 2
    if not client_secret:
        client_secret = getpass.getpass("YOUTUBE_OAUTH_CLIENT_SECRET: ").strip()

    server = http.server.HTTPServer(("127.0.0.1", 0), _Catcher)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/"
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = build_auth_url(client_id, redirect_uri, state, challenge)

    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("Open this link and sign in with the Google account that owns the YouTube channel:\n")
    print(url + "\n")
    if not args.no_browser:
        webbrowser.open(url)
    print(f"Waiting up to {WAIT_SECONDS // 60} minutes for the approval...")
    got = _Catcher.done.wait(WAIT_SECONDS)
    server.shutdown()
    if not got:
        print("Timed out waiting for the approval.", file=sys.stderr)
        return 1

    result = _Catcher.result
    if result.get("state") != state:
        print("The reply did not match this request (state mismatch). Run the script again.", file=sys.stderr)
        return 1
    if "error" in result:
        print(f"Google returned: {result['error']}", file=sys.stderr)
        return 1

    resp = httpx.post(TOKEN_URL, timeout=30, data={
        "code": result["code"],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    })
    if resp.status_code != 200:
        try:
            reason = resp.json().get("error", resp.reason_phrase)
        except ValueError:
            reason = resp.reason_phrase
        print(f"Token exchange failed ({resp.status_code}): {reason}", file=sys.stderr)
        return 1
    tokens = resp.json()
    refresh = tokens.get("refresh_token")
    if not refresh:
        print("Google returned no refresh token. Remove the app's access at "
              "https://myaccount.google.com/permissions and run again.", file=sys.stderr)
        return 1
    granted = set((tokens.get("scope") or "").split())
    missing = [s for s in SCOPES if s not in granted]
    if missing:
        print(f"Warning: not granted: {', '.join(missing)}. The analytics job needs both scopes.",
              file=sys.stderr)

    print("\nAdd this line to the server .env (next to the client id and secret):\n")
    print(f"YOUTUBE_OAUTH_REFRESH_TOKEN={refresh}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
