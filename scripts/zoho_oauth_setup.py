#!/usr/bin/env python3
"""One-time helper to obtain a Zoho refresh token for the CRM Products module.

Reads ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET / ZOHO_REGION from the environment
(or ``--env`` file), opens a browser to Zoho's consent screen, and prints the
resulting refresh token. Use ``--write`` to store it into the .env file.

Scope used: ZohoCRM.modules.products.READ (least privilege for the pipeline).
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from dotenv import load_dotenv  # noqa: E402

SCOPE = "ZohoCRM.modules.products.READ"
REDIRECT_PORT = 8080
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}"

ACCOUNTS_HOSTS = {
    "com": "accounts.zoho.com",
    "eu": "accounts.zoho.eu",
    "in": "accounts.zoho.in",
    "au": "accounts.zoho.com.au",
    "jp": "accounts.zoho.jp",
}

_code: str | None = None
_error: str | None = None


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        global _code, _error
        query = parse_qs(self.path.split("?", 1)[-1])
        if self.path.startswith("/favicon"):
            self.send_response(204)
            self.end_headers()
            return
        _code = (query.get("code") or [None])[0]
        _error = (query.get("error") or [None])[0]
        body = (
            b"Authorization complete. You can close this window."
            if _code and not _error
            else b"Authorization failed."
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence request logging
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Mint a Zoho refresh token for CRM Products")
    parser.add_argument("--env", type=Path, default=None, help=".env file to read client id/secret/region from")
    parser.add_argument("--write", action="store_true", help="Write ZOHO_REFRESH_TOKEN into the .env file")
    args = parser.parse_args()

    if args.env:
        load_dotenv(args.env)
    client_id = os.getenv("ZOHO_CLIENT_ID", "").strip()
    client_secret = os.getenv("ZOHO_CLIENT_SECRET", "").strip()
    region = os.getenv("ZOHO_REGION", "com").strip().lower()
    if not client_id or not client_secret:
        print("ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET must be set (see --env)", file=sys.stderr)
        return 1
    accounts_host = ACCOUNTS_HOSTS.get(region, "accounts.zoho.com")

    global _code, _error
    _code = _error = None
    server = HTTPServer(("localhost", REDIRECT_PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    auth_url = f"https://{accounts_host}/oauth/v2/auth?" + urlencode(
        {
            "scope": SCOPE,
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    print("Opening browser for Zoho consent...")
    webbrowser.open(auth_url)
    deadline = time.time() + 180
    while not _code and not _error and time.time() < deadline:
        time.sleep(0.5)
    server.shutdown()
    if _error or not _code:
        print(f"Authorization failed: {_error or 'timeout'}", file=sys.stderr)
        return 1

    import requests

    resp = requests.post(
        f"https://{accounts_host}/oauth/v2/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": _code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=60,
    )
    if resp.status_code >= 400:
        print(f"Token exchange failed: HTTP {resp.status_code}: {resp.text[:300]}", file=sys.stderr)
        return 1
    payload = resp.json()
    refresh_token = (payload.get("refresh_token") or "").strip()
    if not refresh_token:
        print(f"No refresh_token returned: {payload}", file=sys.stderr)
        return 1
    print(f"\nZOHO_REFRESH_TOKEN={refresh_token}")

    if args.write:
        env_path = args.env or Path(".env")
        if env_path.exists():
            text = env_path.read_text(encoding="utf-8")
            if re.search(r"^ZOHO_REFRESH_TOKEN=", text, re.M):
                text = re.sub(
                    r"^ZOHO_REFRESH_TOKEN=.*$",
                    f"ZOHO_REFRESH_TOKEN={refresh_token}",
                    text,
                    flags=re.M,
                )
            else:
                text += f"\nZOHO_REFRESH_TOKEN={refresh_token}\n"
            env_path.write_text(text, encoding="utf-8")
            print(f"Written to {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
