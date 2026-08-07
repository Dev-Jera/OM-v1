"""Manage follow-up questions and conversation clarification state."""
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class FollowUpManager:
    """Queue and track follow-up questions for a conversation.

    This implementation can operate either on an in-memory conversation_state dict
    (legacy) or on a session store via a StateManager that exposes get_session/update_session.
    """

    def queue_followup(self, conversation_state: Dict[str, Any], question: str) -> None:
        conversation_state.setdefault("followups", []).append({"question": question, "asked": False})
        logger.debug("Queued follow-up (in-memory): %s", question)

    def get_next_followup(self, conversation_state: Dict[str, Any]) -> Optional[str]:
        followups: List[Dict[str, Any]] = conversation_state.get("followups", [])
        for f in followups:
            if not f.get("asked"):
                f["asked"] = True
                logger.debug("Returning next follow-up (in-memory): %s", f.get("question"))
                return f.get("question")
        return None

    def queue_followup_session(self, session_id: str, state_manager, question: str) -> None:
        """Queue a follow-up question in the persistent session store.

        state_manager must implement get_session(session_id) -> dict and update_session(session_id, updates).
        """
        session = state_manager.get_session(session_id) or {}
        followups = session.get("followups", [])
        followups.append({"question": question, "asked": False})
        state_manager.update_session(session_id, {"followups": followups})
        logger.debug("Queued follow-up (session=%s): %s", session_id, question)

    def get_next_followup_session(self, session_id: str, state_manager) -> Optional[str]:
        session = state_manager.get_session(session_id) or {}
        followups: List[Dict[str, Any]] = session.get("followups", [])
        for idx, f in enumerate(followups):
            if not f.get("asked"):
                followups[idx]["asked"] = True
                state_manager.update_session(session_id, {"followups": followups})
                logger.debug("Returning next follow-up (session=%s): %s", session_id, f.get("question"))
                return f.get("question")
        return None

    def create_clarifying_question(self, user_input: str) -> str:
        cleaned = (user_input or "").strip().strip("\"'")
        if cleaned:
            return (
                f"Could you clarify or provide more details? When you say '{cleaned}', which cover did you have in mind? "
                "For example Personal Accident, Serenicare, Motor Private, or Travel Sure Plus."
            )
        return (
            "Could you clarify or provide more details on which cover you have in mind? "
            "For example Personal Accident, Serenicare, Motor Private, or Travel Sure Plus."
        )

    def extract_followup_from_text(self, text: str) -> str:
        # Naive extraction: return the first sentence that ends with a question mark
        sentences = [s.strip() for s in text.split(".") if s.strip()]
        for s in sentences:
            if "?" in s:
                return s
        # fallback: if no question-marked sentence, return whole text limited
        return text if len(text) <= 250 else text[:247] + "..."
