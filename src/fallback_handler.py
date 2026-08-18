"""Fallback handling utilities.

This module provides strategies for generating fallback responses when the model
cannot provide a confident or useful reply.
"""
from typing import Any, Dict, Optional

import logging
from src.integrations.policy.escalation_service import EscalationService

logger = logging.getLogger(__name__)


class FallbackHandler:
    """Generates fallback responses and logs triggers for telemetry.

    Strategies can include:
    - Asking the user to rephrase
    - Offering to connect to a human agent
    - Returning best-effort answer with a disclaimer
    - Providing help topics
    - Escalating to a human agent queue
    """

    def __init__(self, offer_human_threshold: float = 0.35, escalation_service=None):
        self.offer_human_threshold = offer_human_threshold
        self.escalation_service = escalation_service or EscalationService()

    def generate_fallback(
        self,
        user_input: str,
        reason: str = "low_confidence",
        confidence: Optional[float] = None,
        conversation_state: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.info("Generating fallback: reason=%s, confidence=%s", reason, confidence)

        # Low confidence: ask a gentle clarifying question. We do NOT offer a
        # human agent here - the agent is only offered when the user asks for
        # one or declines the completion question.
        if reason == "low_confidence" or (confidence is not None and confidence < self.offer_human_threshold):
            message = (
                "I'm sorry, I didn't quite catch that. Could you rephrase or give me a "
                "little more detail so I can help you better?"
            )
            offer_human = False
        else:
            message = (
                "I didn't fully understand. Could you please rephrase or provide more details?"
            )
            offer_human = False

        # Optionally include suggested help topics based on keywords (very simple)
        suggestions = self._suggest_topics(user_input)

        payload = {
            "message": message,
            "fallback": True,
            "follow_up": True,
            "offer_human": offer_human,
            "suggestions": suggestions,
            "metadata": {"reason": reason, "confidence": confidence},
        }

        # Update conversation_state if provided
        if conversation_state is not None:
            conversation_state.setdefault("fallbacks", []).append(payload)

        return payload

    @staticmethod
    def _suggest_topics(user_input: str):
        if not user_input:
            return []
        lowered = user_input.lower()
        suggestions = []
        if "claim" in lowered:
            suggestions.append("claims")
        if "premium" in lowered or "price" in lowered:
            suggestions.append("pricing")
        if "policy" in lowered or "coverage" in lowered:
            suggestions.append("policies")
        return suggestions
