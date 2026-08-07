"""
Escalation Service

Handles routing of complex or low-confidence cases to a human agent queue.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EscalationService:
    def __init__(self, queue_backend=None, state_manager=None):
        # queue_backend could be a database, message queue, or API client
        self.queue_backend = queue_backend
        self.state_manager = state_manager

    def escalate_to_human(self, session_id: str, reason: str, user_id: Optional[str] = None, metadata: Optional[dict] = None):
        """
        Escalate the session to a human agent queue and mark session as escalated.
        """
        logger.info(f"Escalating session {session_id} to human agent. Reason: {reason}")
        escalation_record = {
            "session_id": session_id,
            "user_id": user_id,
            "reason": reason,
            "metadata": metadata or {},
        }
        # Mark session as escalated in state manager (DB, Redis, etc.)
        if self.state_manager:
            self.state_manager.mark_escalated(session_id, reason=reason, metadata=metadata or {})
        # Add to queue for agents
        if self.queue_backend:
            self.queue_backend.add_to_queue(escalation_record)
        else:
            logger.warning("No queue backend configured. Escalation not persisted.")
        return escalation_record

    def agent_join(self, session_id: str, agent_id: str):
        """
        Called when a human agent joins the chat. Updates session state.
        """
        logger.info(f"Agent {agent_id} joining session {session_id}")
        if self.state_manager:
            self.state_manager.mark_agent_joined(session_id, agent_id)

    def end_escalation(self, session_id: str):
        """
        Called when the agent or user ends the live chat. Returns session to bot mode.
        """
        logger.info(f"Ending escalation for session {session_id}")
        if self.state_manager:
            self.state_manager.end_escalation(session_id)
