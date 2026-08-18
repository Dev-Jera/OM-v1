"""Zoho OAuth token management for the CRM REST API.

Handles the refresh-token flow to obtain and cache a short-lived access token.
All credentials come from environment variables and are never logged or stored.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

ACCOUNTS_HOSTS = {
    "com": "accounts.zoho.com",
    "eu": "accounts.zoho.eu",
    "in": "accounts.zoho.in",
    "au": "accounts.zoho.com.au",
    "jp": "accounts.zoho.jp",
}

API_HOSTS = {
    "com": "www.zohoapis.com",
    "eu": "www.zohoapis.eu",
    "in": "www.zohoapis.in",
    "au": "www.zohoapis.com.au",
    "jp": "www.zohoapis.jp",
}

DEFAULT_REGION = "com"

# Refresh the token a little before it actually expires to avoid races.
TOKEN_EXPIRY_BUFFER_SECONDS = 60


class ZohoOAuthError(RuntimeError):
    """Raised when Zoho OAuth token acquisition or refresh fails."""


def _region_hosts(region: str) -> tuple[str, str]:
    region = (region or DEFAULT_REGION).strip().lower()
    accounts = ACCOUNTS_HOSTS.get(region)
    api = API_HOSTS.get(region)
    if not accounts or not api:
        raise ZohoOAuthError(
            f"Unsupported Zoho region: {region!r} (supported: {', '.join(ACCOUNTS_HOSTS)})"
        )
    return accounts, api


class ZohoTokenManager:
    """Caches and refreshes a Zoho CRM access token from a refresh token."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        region: str = DEFAULT_REGION,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.region = region
        self._accounts_host, self._api_host = _region_hosts(region)
        self._session = session or requests.Session()
        self._lock = threading.Lock()
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0

    @property
    def api_base_url(self) -> str:
        return f"https://{self._api_host}"

    def _access_token_expired(self) -> bool:
        return time.time() >= self._expires_at

    def _refresh(self) -> str:
        url = f"https://{self._accounts_host}/oauth/v2/token"
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        }
        try:
            resp = self._session.post(url, data=data, timeout=60)
        except requests.RequestException as exc:
            raise ZohoOAuthError(f"Zoho token refresh failed (network): {exc}") from exc
        if resp.status_code >= 400:
            raise ZohoOAuthError(
                f"Zoho token refresh failed: HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ZohoOAuthError(f"Zoho token refresh returned invalid JSON: {exc}") from exc
        access_token = payload.get("access_token")
        if not access_token:
            raise ZohoOAuthError(f"Zoho token refresh returned no access_token: {payload}")
        expires_in = int(payload.get("expires_in") or 3600)
        self._access_token = access_token
        self._expires_at = time.time() + max(expires_in - TOKEN_EXPIRY_BUFFER_SECONDS, 60)
        return access_token

    def get_access_token(self, force: bool = False) -> str:
        """Return a valid access token, refreshing if cached one is stale."""
        with self._lock:
            if not force and self._access_token and not self._access_token_expired():
                return self._access_token
            return self._refresh()
