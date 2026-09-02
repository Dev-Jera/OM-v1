"""
Session and state management for chatbot
"""

from typing import Dict, Optional, Any
from datetime import datetime
import uuid
import logging

logger = logging.getLogger(__name__)


class StateManager:
    def __init__(self, redis_cache, postgres_db):
        self.redis = redis_cache
        self.db = postgres_db

    def create_session(self, user_id: str, mode: str = "conversational") -> str:
        """Create new session"""
        session_id = str(uuid.uuid4())

        # Create in PostgreSQL
        conversation = self.db.create_conversation(user_id, mode)

        # Initialize in Redis
        session_data = {
            "session_id": session_id,
            "conversation_id": str(conversation.id),
            "user_id": user_id,
            "mode": mode,
            "current_flow": None,
            "current_step": 0,
            "collected_data": {},
            "context": {},
            "created_at": datetime.utcnow().isoformat(),
        }

        self.redis.set_session(session_id, session_data, ttl=86400)

        return session_id

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data"""
        return self.redis.get_session(session_id)

    def update_session(self, session_id: str, updates: Dict[str, Any]):
        """Update session data"""
        self.redis.update_session(session_id, updates)

    # --- Escalation state ----------------------------------------------------

    def get_escalation_state(self, session_id: str) -> Dict[str, Any]:
        """Get escalation state with DB fallback if session cache is stale."""
        session = self.get_session(session_id) or {}
        escalated = bool(session.get("escalated", False))
        agent_id = session.get("agent_id")
        reason = session.get("escalation_reason")

        db_state = None
        if hasattr(self.db, "get_escalation_state"):
            try:
                db_state = self.db.get_escalation_state(session_id)
            except Exception:
                db_state = None

        if db_state:
            escalated = bool(db_state.get("escalated", escalated))
            agent_id = db_state.get("agent_id", agent_id)
            reason = db_state.get("escalation_reason", reason)

        return {
            "session_id": session_id,
            "escalated": escalated,
            "agent_id": agent_id,
            "escalation_reason": reason,
            "db_state": db_state,
        }

    def mark_escalated(self, session_id: str, reason: str = None, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Mark a session as escalated in cache and DB."""
        session = self.get_session(session_id) or {}
        updates = {"escalated": True, "agent_id": None}
        if reason:
            updates["escalation_reason"] = reason
        self.update_session(session_id, updates)

        if hasattr(self.db, "mark_escalated"):
            try:
                self.db.mark_escalated(
                    session_id=session_id,
                    conversation_id=session.get("conversation_id"),
                    user_id=session.get("user_id"),
                    reason=reason,
                    metadata=metadata or {},
                )
            except Exception:
                pass

        return self.get_escalation_state(session_id)

    def mark_agent_joined(self, session_id: str, agent_id: str) -> Dict[str, Any]:
        """Mark that an agent has joined this escalated session."""
        previous_state = self.get_escalation_state(session_id)
        already_joined = bool(previous_state.get("escalated")) and str(previous_state.get("agent_id") or "") == str(agent_id or "")

        self.update_session(session_id, {"escalated": True, "agent_id": agent_id})
        session = self.get_session(session_id) or {}
        conversation_id = session.get("conversation_id")
        if not already_joined and conversation_id and hasattr(self.db, "add_conversation_event"):
            try:
                self.db.add_conversation_event(
                    conversation_id=conversation_id,
                    event_type="agent_joined",
                    payload={"agent_id": str(agent_id)},
                )
            except Exception:
                pass
        if not already_joined and hasattr(self.db, "mark_agent_joined"):
            try:
                self.db.mark_agent_joined(session_id=session_id, agent_id=agent_id)
            except Exception:
                pass
        return self.get_escalation_state(session_id)

    def end_escalation(self, session_id: str) -> Dict[str, Any]:
        """Clear escalation state for a session."""
        self.update_session(session_id, {"escalated": False, "agent_id": None, "escalation_reason": None})
        if hasattr(self.db, "end_escalation"):
            try:
                self.db.end_escalation(session_id=session_id)
            except Exception:
                pass
        return self.get_escalation_state(session_id)

    def switch_mode(self, session_id: str, new_mode: str, flow: str = None):
        """Switch between conversational and guided mode"""
        updates = {"mode": new_mode, "current_flow": flow, "current_step": 0 if new_mode == "guided" else None}
        self.update_session(session_id, updates)

    def advance_step(self, session_id: str, collected_data: Dict[str, Any] = None):
        """Advance to next step in guided flow"""
        session = self.get_session(session_id)
        if session:
            updates = {"current_step": session["current_step"] + 1}
            if collected_data:
                session["collected_data"].update(collected_data)
                updates["collected_data"] = session["collected_data"]

            self.update_session(session_id, updates)

    def set_flow(self, session_id: str, flow_name: str):
        """Set current flow"""
        self.update_session(session_id, {"current_flow": flow_name, "current_step": 0})

    def get_collected_data(self, session_id: str) -> Dict[str, Any]:
        """Get all collected data from current flow"""
        session = self.get_session(session_id)
        return session.get("collected_data", {}) if session else {}

    def clear_collected_data(self, session_id: str):
        """Clear collected data"""
        self.update_session(session_id, {"collected_data": {}})

    def end_session(self, session_id: str, ended_by: str = "user"):
        """End session and clean up."""
        session = self.get_session(session_id)
        if not session:
            return

        conversation_id = session.get("conversation_id")
        session_context = dict(session.get("context") or {})
        user_id = session.get("user_id")

        if conversation_id and hasattr(self.db, "end_conversation"):
            try:
                self.db.end_conversation(conversation_id)
            except Exception:
                pass

        if conversation_id and hasattr(self.db, "add_conversation_event"):
            try:
                self.db.add_conversation_event(
                    conversation_id=conversation_id,
                    event_type="session_end",
                    payload={"ended_by": str(ended_by or "user")},
                )
            except Exception:
                pass

        # Push conversation to Zoho CRM (fire-and-forget, reads data BEFORE Redis deletion)
        try:
            from src.integrations.zoho.conversation_push import push_conversation_to_zoho

            conversation_obj = None
            if conversation_id and hasattr(self.db, "get_conversation"):
                try:
                    conversation_obj = self.db.get_conversation(conversation_id)
                except Exception:
                    pass

            push_conversation_to_zoho(
                conversation_id=conversation_id,
                user_id=user_id,
                session_context=session_context,
                db=self.db,
                conversation=conversation_obj,
                background=True,
            )
            logger.info(
                "[DBG-CONV][PUSH] session_id=%s conversation_id=%s",
                session_id,
                conversation_id,
            )
        except Exception:
            pass

        # Delete from Redis
        self.redis.delete_session(session_id)

    # --- Form drafts ---------------------------------------------------------

    def save_form_draft(self, session_id: str, flow_name: str, draft: Dict[str, Any]):
        """Persist a multi-step form draft in Redis."""
        self.redis.set_form_draft(session_id, flow_name, draft)

    def get_form_draft(self, session_id: str, flow_name: str) -> Optional[Dict[str, Any]]:
        """Fetch a form draft from Redis."""
        return self.redis.get_form_draft(session_id, flow_name)

    def clear_form_draft(self, session_id: str, flow_name: str) -> None:
        """Remove a form draft from Redis."""
        self.redis.delete_form_draft(session_id, flow_name)
