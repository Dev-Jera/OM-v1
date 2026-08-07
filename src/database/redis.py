"""
Lightweight in-memory RedisCache replacement for local development.

This implements just enough of the interface used by the chatbot
`StateManager` so that the FastAPI app can run without a real Redis
instance.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class RedisCache:
    def __init__(self) -> None:
        # Simple in-memory store: session_id -> data
        self._sessions: Dict[str, Dict[str, Any]] = {}
        # In-memory form drafts: (session_id, flow_name) -> data
        self._form_drafts: Dict[str, Dict[str, Any]] = {}

    # --- Session helpers used by StateManager ---------------------------------

    def set_session(self, session_id: str, data: Dict[str, Any], ttl: int = 1800) -> None:
        # TTL is ignored in this in-memory implementation.
        self._sessions[session_id] = dict(data)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._sessions.get(session_id)

    def update_session(self, session_id: str, updates: Dict[str, Any]) -> None:
        if session_id not in self._sessions:
            return
        self._sessions[session_id].update(updates)

    def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    # --- Form draft helpers --------------------------------------------------

    def _draft_key(self, session_id: str, flow_name: str) -> str:
        return f"{session_id}:{flow_name}"

    def set_form_draft(self, session_id: str, flow_name: str, data: Dict[str, Any], ttl: int = 604800) -> None:
        # TTL is ignored in this in-memory implementation.
        self._form_drafts[self._draft_key(session_id, flow_name)] = dict(data)

    def get_form_draft(self, session_id: str, flow_name: str) -> Optional[Dict[str, Any]]:
        return self._form_drafts.get(self._draft_key(session_id, flow_name))

    def update_form_draft(self, session_id: str, flow_name: str, updates: Dict[str, Any]) -> None:
        key = self._draft_key(session_id, flow_name)
        if key not in self._form_drafts:
            return
        self._form_drafts[key].update(updates)

    def delete_form_draft(self, session_id: str, flow_name: str) -> None:
        self._form_drafts.pop(self._draft_key(session_id, flow_name), None)

    # --- Misc -----------------------------------------------------------------

    def ping(self) -> bool:
        """
        FastAPI health check calls this; always return True so the API reports
        Redis as "connected" in local/dev mode.
        """
        return True
