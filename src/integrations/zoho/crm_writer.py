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

    def _request(
        self,
        method: str,
        url: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {"timeout": 60}
        if json_body is not None:
            kwargs["json"] = json_body
        if params:
            kwargs["params"] = params

        resp = self.session.request(method, url, headers=self._headers(), **kwargs)
        if resp.status_code == 401:
            token = self.token_manager.get_access_token(force=True)
            headers = {
                "Authorization": f"Zoho-oauthtoken {token}",
                "Content-Type": "application/json",
            }
            resp = self.session.request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise ZohoCRMError(f"Zoho CRM {method} {url} failed: HTTP {resp.status_code}: {resp.text[:300]}")
        if not getattr(resp, "text", "") and resp.status_code == 204:
            return {}
        return resp.json()

    def create(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create records in the module. Returns the raw CRM response."""
        url = f"{self.token_manager.api_base_url}/crm/v2/{self.module}"
        return self._request("POST", url, {"data": records})

    def update(self, record_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update one existing record by id. Returns the raw CRM response."""
        url = f"{self.token_manager.api_base_url}/crm/v2/{self.module}/{record_id}"
        return self._request("PUT", url, {"data": [data]})

    @staticmethod
    def _key_fields(record: Dict[str, Any], duplicate_check_fields: List[str]) -> List[str]:
        """The record's matching keys: the requested fields plus ``Name``.

        ``Name`` is the natural per-record unique key in this codebase (daily
        = ``2026-08-28``, hourly = ``2026-08-28-12``). Requiring it too keeps a
        daily key from colliding with an intraday row whose ``Metric_Date``
        happens to equal the same date.
        """
        fields = list(duplicate_check_fields)
        if record.get("Name") not in (None, ""):
            fields.append("Name")
        return fields

    def _matches_keys(
        self, row: Dict[str, Any], record: Dict[str, Any], duplicate_check_fields: List[str]
    ) -> bool:
        """Exact key-match with None/absent treated as the same bucket.

        Catches the Zoho null-field mismatch (a daily record has Metric_Hour
        empty; an hourly record has it set) so a daily key never collides
        with an intraday row whose only other key happens to be the same date.
        """
        for field in self._key_fields(record, duplicate_check_fields):
            want = record.get(field)
            got = row.get(field)
            want_empty = want is None or want == ""
            got_empty = got is None or got == ""
            if want_empty != got_empty:
                return False
            if not want_empty and str(want) != str(got):
                return False
        return True

    def _find_existing(self, record: Dict[str, Any], duplicate_check_fields: List[str]) -> Optional[str]:
        """Search the module for a record matching the key fields; return its id.

        Uses the record-list endpoint with a criteria filter (same API scope
        as create/update) rather than Zoho's built-in upsert duplicate-check,
        which only honours fields configured as *unique* in the module.
        """
        present = [f for f in self._key_fields(record, duplicate_check_fields) if record.get(f) not in (None, "")]
        if not present:
            return None

        criteria_parts = [f"{field}:equals:{record[field]}" for field in present]
        url = f"{self.token_manager.api_base_url}/crm/v2/{self.module}"
        resp = self._request(
            "GET",
            url,
            params={"criteria": f"({' and '.join(criteria_parts)})", "per_page": "25"},
        )
        candidates = sorted(
            (row for row in (resp.get("data") or []) if self._matches_keys(row, record, duplicate_check_fields)),
            key=lambda r: str(r.get("id", "")),
        )
        if not candidates:
            return None
        return str(candidates[-1].get("id")) if candidates[-1].get("id") is not None else None

    def upsert_by_key(self, records: List[Dict[str, Any]], key_field: str) -> Dict[str, Any]:
        """Insert-or-update records keyed by a single business field.

        Used by live conversation pushes so re-pushing the same
        ``Conversation_ID`` (as the transcript grows) updates the existing
        record instead of creating duplicates. Insert-only when the key field
        is missing/empty.
        """
        responses: List[Dict[str, Any]] = []
        for record in records:
            key_value = record.get(key_field)
            existing_id = None
            if key_value not in (None, ""):
                existing_id = self._find_existing(record, [key_field])
            if existing_id is not None:
                resp = self.update(existing_id, record)
            else:
                resp = self._request(
                    "POST",
                    f"{self.token_manager.api_base_url}/crm/v2/{self.module}",
                    {"data": [record]},
                )
            responses.append(resp)
        return {"data": responses}

    def upsert(self, records: List[Dict[str, Any]], duplicate_check_fields: List[str]) -> Dict[str, Any]:
        """Insert-or-update records keyed by the given unique fields.

        Idempotent by design: pushing the same day/hour twice updates the
        existing record instead of duplicating it. We search-first because
        Zoho's built-in duplicate-check only works on module fields configured
        as unique.
        """
        responses: List[Dict[str, Any]] = []
        for record in records:
            existing_id = self._find_existing(record, duplicate_check_fields)
            if existing_id is not None:
                resp = self.update(existing_id, record)
            else:
                resp = self._request(
                    "POST",
                    f"{self.token_manager.api_base_url}/crm/v2/{self.module}",
                    {"data": [record]},
                )
            responses.append(resp)
        return {"data": responses}