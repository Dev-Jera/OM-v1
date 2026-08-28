"""
Chat router - Determines mode and routes messages
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ChatRouter:
    def __init__(self, conversational_mode, guided_mode, state_manager, product_matcher):
        self.conversational = conversational_mode
        self.guided = guided_mode
        self.state_manager = state_manager
        self.product_matcher = product_matcher

    async def route(
        self,
        message: str,
        session_id: str,
        user_id: str,
        form_data: Optional[Dict[str, Any]] = None,
        db=None,
    ) -> Dict:
        """Route message to appropriate mode. form_data is used as user_input in guided flows when set."""

        # Get session state
        session = self.state_manager.get_session(session_id)

        if not session:
            # Create new session
            session_id = self.state_manager.create_session(user_id)
            session = self.state_manager.get_session(session_id)

        # For exit intent we need the raw message
        effective_message = (message or "").strip() if form_data is None else ""
        if self._is_exit_intent(effective_message or str(message)) and session.get("mode") == "guided":
            self.state_manager.switch_mode(session_id, "conversational")
            return {"message": "👋 Exited guided flow. How else can I help you?", "mode": "conversational"}

        # Resolve any pending chat-to-guided confirmation before routing elsewhere.
        pending_switch = self._get_pending_guided_switch(session)

        if form_data and isinstance(form_data, dict):
            action = str(form_data.get("action") or "").strip().lower()

            if action == "confirm_guided_switch" and pending_switch:
                self._clear_pending_guided_switch(session_id, session)
                return await self.guided.start_flow(
                    "journey",
                    session_id,
                    user_id,
                    initial_data=self._build_initial_data_from_pending(pending_switch),
                )

            if action == "cancel_guided_switch" and pending_switch:
                self._clear_pending_guided_switch(session_id, session)
                return {
                    "mode": "conversational",
                    "response": "No problem — we can stay in chat, and I can still answer your questions here.",
                }

        if form_data is None and pending_switch:
            user_reply = (message or "").strip()
            if self._is_confirmation_intent(user_reply):
                self._clear_pending_guided_switch(session_id, session)
                return await self.guided.start_flow(
                    "journey",
                    session_id,
                    user_id,
                    initial_data=self._build_initial_data_from_pending(pending_switch),
                )

            if self._is_decline_intent(user_reply):
                self._clear_pending_guided_switch(session_id, session)
                return {
                    "mode": "conversational",
                    "response": "No problem — we can stay in chat, and I can still answer your questions here.",
                }

            # User moved on with a different topic; avoid stale confirmations.
            if user_reply and not self._is_guided_trigger(user_reply):
                self._clear_pending_guided_switch(session_id, session)

        # Button actions from the frontend to start guided mode and immediately return the first form
        if form_data and isinstance(form_data, dict):
            action = str(form_data.get("action") or form_data.get("type") or "").strip().lower()

            if action == "connect_agent":
                from src.integrations.policy.escalation_service import EscalationService
                EscalationService(state_manager=self.state_manager).escalate_to_human(
                    session_id=session_id,
                    reason="customer_requested_agent",
                    user_id=user_id,
                )
                conversation_id = session.get("conversation_id")
                db_ref = db if db is not None else getattr(self.state_manager, "db", None)
                if db_ref is not None and hasattr(db_ref, "add_conversation_event"):
                    try:
                        db_ref.add_conversation_event(
                            conversation_id=conversation_id,
                            event_type="escalation_confirmed",
                            payload={"source": "button", "reason": "customer_requested_agent"},
                        )
                        from src.chatbot.paths import record_conversation_path
                        record_conversation_path(db_ref, conversation_id, "direct_agent", "button")
                    except Exception:
                        pass
                return {
                    "mode": "escalated",
                    "response": {
                        "type": "agent_connected",
                        "message": "I'm connecting you with one of our support agents. An agent will join this chat momentarily. Please standby...",
                    },
                    "complete": True,
                }

            if action in ("get_quotation", "get_quote"):
                # Redirect to main menu instead of starting guided flow
                ctx = (session.get("context") or {}) if isinstance(session, dict) else {}
                topic = (ctx.get("product_topic") or {}) if isinstance(ctx, dict) else {}
                product_flow = topic.get("digital_flow")
                
                if product_flow:
                    return {
                        "mode": "conversational",
                        "response": "For quotes, please go to the main menu and click 'Get Quote' to follow the steps there.",
                        "suggested_action": {
                            "type": "redirect_to_main_menu",
                            "message": "For quotes, please go to the main menu and click 'Get Quote' to follow the steps there."
                        }
                    }
                else:
                    return {
                        "mode": "conversational",
                        "response": "To get a quote, please go to the main menu and click 'Get Quote' to select a product and follow the steps.",
                        "suggested_action": {
                            "type": "redirect_to_main_menu",
                            "message": "To get a quote, please go to the main menu and click 'Get Quote' to select a product and follow the steps."
                        }
                    }

            if action == "start_guided":
                flow_name = form_data.get("flow") or form_data.get("flow_name") or "journey"
                initial_data = form_data.get("initial_data") or {}
                return await self.guided.start_flow(str(flow_name), session_id, user_id, initial_data=initial_data)

        # If in guided mode, stay in guided unless exiting
        if session.get("mode") == "guided" and session.get("current_flow"):
            user_input = form_data if form_data is not None else message
            return await self.guided.process(user_input, session_id, user_id)

        # Check for guided flow triggers (only when no form_data)
        if form_data is None and self._is_guided_trigger(message):
            flow_type = self._detect_flow_type(message)
            self._set_pending_guided_switch(session_id, session, flow_type)

            flow_label = self._flow_label(flow_type)
            response_text = (
                f"I can guide you through {flow_label} to get your quote. "
                "Would you like me to proceed?"
            )

            logger.info(
                "[Router] Guided trigger detected, awaiting confirmation: message='%s' flow_type=%s",
                message[:100], flow_type
            )

            return {
                "mode": "conversational",
                "response": response_text,
                "suggested_action": {
                    "type": "switch_to_guided",
                    "message": response_text,
                    "flow": "journey",
                    "initial_data": self._build_initial_data_from_pending({"flow_type": flow_type}),
                    "buttons": [
                        {"label": "Yes, proceed", "action": "confirm_guided_switch"},
                        {"label": "Not now", "action": "cancel_guided_switch"},
                    ],
                },
            }
        # Default to conversational mode
        return await self.conversational.process(message, session_id, user_id, form_data=form_data, db=db)

    def _is_guided_trigger(self, message: str) -> bool:
        """Check if message should trigger guided flow.
        Now only triggers for explicit agent/human requests.
        Quote/quotation requests are handled by redirecting to main menu."""
        message_lower = message.lower()

        # Only trigger for explicit agent/human requests
        agent_triggers = [
            "talk to agent",
            "speak to agent",
            "human agent",
            "connect to agent",
            "speak to human",
            "talk to human",
            "human please",
            "agent please",
        ]

        if any(trigger in message_lower for trigger in agent_triggers):
            logger.info("[Router] Agent request trigger matched: %s", message[:100])
            return True

        return False

    def _detect_flow_type(self, message: str) -> str:
        """Detect which guided flow to start.
        Quote/quotation requests now return 'discovery' to redirect to main menu."""
        message_lower = message.lower()

        # Personal Accident: apply, buy, get cover for personal accident
        if any(phrase in message_lower for phrase in ["personal accident", "pa insurance", "accident cover", "pa cover"]):
            return "personal_accident"

        # Travel Insurance: travel insurance, travel sure, travel cover
        if any(phrase in message_lower for phrase in ["travel insurance", "travel sure", "travel cover", "travel policy"]):
            return "travel_insurance"

        # Motor Private: car, vehicle, motor insurance
        if any(
            phrase in message_lower
            for phrase in [
                "motor private",
                "motor insurance",
                "car insurance",
                "vehicle insurance",
                "motor cover",
                "car cover",
            ]
        ):
            return "motor_private"

        # Serenicare: health, medical, serenicare
        if any(
            phrase in message_lower
            for phrase in [
                "serenicare",
                "health insurance",
                "medical cover",
                "medical insurance",
                "health cover",
                "family health",
            ]
        ):
            return "serenicare"

        # Quote/buy triggers - now return 'discovery' to redirect to main menu
        if any(word in message_lower for word in ["quote", "how much", "price", "cost"]):
            return "discovery"

        # Discovery triggers
        if any(word in message_lower for word in ["help me choose", "recommend", "which"]):
            return "discovery"

        # Default to discovery
        return "discovery"

    def _is_exit_intent(self, message: str) -> bool:
        """Check if user wants to exit guided flow"""
        exits = ["exit", "cancel", "stop", "go back", "start over", "nevermind", "not now"]

        message_lower = message.lower()
        return any(exit in message_lower for exit in exits)

    def _is_confirmation_intent(self, message: str) -> bool:
        """Check if user confirmed proceeding to guided flow."""
        text = (message or "").strip().lower()
        if not text:
            return False
        confirmations = {
            "yes",
            "y",
            "yeah",
            "yep",
            "sure",
            "ok",
            "okay",
            "proceed",
            "continue",
            "confirm",
            "go ahead",
            "let's go",
            "start",
        }
        return text in confirmations or any(token in text for token in ["go ahead", "proceed", "continue", "yes"])

    def _is_decline_intent(self, message: str) -> bool:
        """Check if user declined proceeding to guided flow."""
        text = (message or "").strip().lower()
        if not text:
            return False
        declines = {
            "no",
            "n",
            "nope",
            "nah",
            "not now",
            "later",
            "cancel",
            "stop",
        }
        return text in declines or "not now" in text

    def _flow_label(self, flow_type: str) -> str:
        labels = {
            "personal_accident": "Personal Accident",
            "travel_insurance": "Travel Insurance",
            "motor_private": "Motor Private",
            "serenicare": "Serenicare",
        }
        return labels.get(flow_type, "guided support")

    def _build_initial_data_from_pending(self, pending_switch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        flow_type = str((pending_switch or {}).get("flow_type") or "").strip()
        if flow_type in ("personal_accident", "travel_insurance", "motor_private", "serenicare"):
            return {"product_flow": flow_type}
        return None

    def _get_pending_guided_switch(self, session: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(session, dict):
            return None
        ctx = session.get("context") or {}
        if not isinstance(ctx, dict):
            return None
        pending = ctx.get("pending_guided_switch")
        return pending if isinstance(pending, dict) else None

    def _set_pending_guided_switch(self, session_id: str, session: Dict[str, Any], flow_type: str) -> None:
        ctx = (session.get("context") or {}) if isinstance(session, dict) else {}
        if not isinstance(ctx, dict):
            ctx = {}
        ctx["pending_guided_switch"] = {"flow_type": flow_type}
        self.state_manager.update_session(session_id, {"context": ctx})

    def _clear_pending_guided_switch(self, session_id: str, session: Optional[Dict[str, Any]]) -> None:
        if not isinstance(session, dict):
            return
        ctx = session.get("context") or {}
        if not isinstance(ctx, dict):
            return
        if "pending_guided_switch" in ctx:
            ctx.pop("pending_guided_switch", None)
            self.state_manager.update_session(session_id, {"context": ctx})