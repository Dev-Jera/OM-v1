"""Zoho CRM Products module collector.

Fetches product catalogue records from the Zoho CRM Products module via the
REST API, paginated, with automatic access-token refresh on 401 responses.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

from src.integrations.zoho.oauth import ZohoTokenManager

logger = logging.getLogger(__name__)

PAGE_SIZE = 200


class ZohoCRMError(RuntimeError):
    """Raised when a Zoho CRM API request fails."""


class ZohoCRMProductsCollector:
    """Pull product records from the Zoho CRM Products module."""

    def __init__(
        self,
        token_manager: ZohoTokenManager,
        session: Optional[requests.Session] = None,
        module: str = "Products",
        fields: Optional[List[str]] = None,
    ) -> None:
        self.token_manager = token_manager
        self.session = session or requests.Session()
        self.module = module
        self.fields = fields

    def _headers(self, access_token: str) -> dict:
        return {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json",
        }

    def _get(self, url: str, params: dict) -> Dict[str, Any]:
        access_token = self.token_manager.get_access_token()
        resp = self.session.get(url, params=params, headers=self._headers(access_token), timeout=90)
        if resp.status_code == 401:
            logger.info("Zoho access token rejected; refreshing and retrying once")
            access_token = self.token_manager.get_access_token(force=True)
            resp = self.session.get(url, params=params, headers=self._headers(access_token), timeout=90)
        if resp.status_code >= 400:
            raise ZohoCRMError(
                f"Zoho CRM {self.module} request failed: HTTP {resp.status_code}: {resp.text[:400]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise ZohoCRMError(f"Zoho CRM returned invalid JSON: {exc}") from exc

    def fetch_records(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch product records, paging through the CRM until all are read.

        Args:
            limit: Stop after this many records (for quick free-tier tests).

        Returns:
            List of raw Zoho CRM record dicts.
        """
        records: List[Dict[str, Any]] = []
        page = 1
        while True:
            params: Dict[str, Any] = {"page": page, "per_page": PAGE_SIZE}
            if self.fields:
                params["fields"] = ",".join(self.fields)
            url = f"{self.token_manager.api_base_url}/crm/v2/{self.module}"
            data = self._get(url, params)
            records.extend(data.get("data") or [])
            if limit is not None and len(records) >= limit:
                return records[:limit]
            info = data.get("info") or {}
            if not info.get("more_records"):
                break
            page += 1
        return records
