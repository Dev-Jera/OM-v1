"""Thin Zoho CRM write client (create / upsert).

Counterpart to the read-only collector: used by the daily KPI push and the
escalation handoff. Reuses the shared token manager and the same 401-retry
behaviour as the collector.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

from src.integrations.zoho.collectors.crm_products import ZohoCRMError

logger = logging.getLogger(__name__)


class ZohoCRMWriter:
    def __init__(self, token_manager: Any, module: str, session: Optional[requests.Session] = None):
        self.token_manager = token_manager
        self.module = module
        self.session = session or requests.Session()

    def _headers(self) -> Dict[str, str]:
        token = self.token_manager.get_access_token()
        return {
            "Authorization": f"Zoho-oauthtoken {token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, url: str, json_body: Dict[str, Any]) -> Dict[str, Any]:
        resp = self.session.request(
            method, url, json=json_body, headers=self._headers(), timeout=60
        )
        if resp.status_code == 401:
            token = self.token_manager.get_access_token(force=True)
            headers = {
                "Authorization": f"Zoho-oauthtoken {token}",
                "Content-Type": "application/json",
            }
            resp = self.session.request(method, url, json=json_body, headers=headers, timeout=60)
        if resp.status_code >= 400:
            raise ZohoCRMError(f"Zoho CRM {method} {url} failed: HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def create(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create records in the module. Returns the raw CRM response."""
        url = f"{self.token_manager.api_base_url}/crm/v2/{self.module}"
        return self._request("POST", url, {"data": records})

    def upsert(self, records: List[Dict[str, Any]], duplicate_check_fields: List[str]) -> Dict[str, Any]:
        """Insert-or-update records keyed by the given unique fields.

        Idempotent by design: pushing the same day twice updates the existing
        record instead of duplicating it.
        """
        url = f"{self.token_manager.api_base_url}/crm/v2/{self.module}/upsert"
        body = {"data": records, "duplicate_check_fields": duplicate_check_fields}
        return self._request("PUT", url, body)
