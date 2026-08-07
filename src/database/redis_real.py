"""
Real Redis-backed cache for production when REDIS_URL (and optionally
USE_POSTGRES_CONVERSATIONS) are set. Implements the same interface as
src.database.redis (in-memory stub).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import redis


class RedisCache:
    """
    Redis-backed session cache. Use when REDIS_URL is set in production.
    """

    def __init__(self, url: str, default_ttl: int = 1800, draft_ttl: int = 604800) -> None:
        self._client = redis.from_url(url, decode_responses=True)
        self._default_ttl = default_ttl
        self._draft_ttl = draft_ttl

    def set_session(self, session_id: str, data: Dict[str, Any], ttl: int = 1800) -> None:
        key = f"session:{session_id}"
        payload = json.dumps(data, default=str)
        self._client.setex(key, ttl or self._default_ttl, payload)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        key = f"session:{session_id}"
        raw = self._client.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def update_session(self, session_id: str, updates: Dict[str, Any]) -> None:
        existing = self.get_session(session_id)
        if not existing:
            return
        existing.update(updates)
        self.set_session(session_id, existing, ttl=self._default_ttl)

    def delete_session(self, session_id: str) -> None:
        self._client.delete(f"session:{session_id}")

    # --- Form draft helpers --------------------------------------------------

    def _draft_key(self, session_id: str, flow_name: str) -> str:
        return f"form_draft:{flow_name}:{session_id}"

    def set_form_draft(self, session_id: str, flow_name: str, data: Dict[str, Any], ttl: int = 604800) -> None:
        key = self._draft_key(session_id, flow_name)
        payload = json.dumps(data, default=str)
        self._client.setex(key, ttl or self._draft_ttl, payload)

    def get_form_draft(self, session_id: str, flow_name: str) -> Optional[Dict[str, Any]]:
        key = self._draft_key(session_id, flow_name)
        raw = self._client.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def update_form_draft(self, session_id: str, flow_name: str, updates: Dict[str, Any]) -> None:
        existing = self.get_form_draft(session_id, flow_name)
        if not existing:
            return
        existing.update(updates)
        self.set_form_draft(session_id, flow_name, existing, ttl=self._draft_ttl)

    def delete_form_draft(self, session_id: str, flow_name: str) -> None:
        self._client.delete(self._draft_key(session_id, flow_name))

    def ping(self) -> bool:
        try:
            return self._client.ping()
        except Exception:
            return False
