"""
Guided mode - Structured conversation flows
"""

from typing import Dict
from datetime import datetime
from ..flows.product_discovery import ProductDiscoveryFlow
from ..flows.payment import PaymentFlow
from ..flows.motor_private import MotorPrivateFlow
from ..flows.personal_accident import PersonalAccidentFlow
from ..flows.travel_insurance import TravelInsuranceFlow
from ..flows.serenicare import SerenicareFlow
from ..flows.dynamic_question_engine import DynamicQuestionEngineFlow


class GuidedMode:
    TRAVEL_INSURANCE_FLOW_VERSION = 2

    def __init__(self, state_manager, product_catalog, db):
        self.state_manager = state_manager
        self.catalog = product_catalog
        self.db = db

        # Initialize flows
        self.flows = {
            "journey": DynamicQuestionEngineFlow(product_catalog, db),
            "discovery": ProductDiscoveryFlow(product_catalog),
            "payment": PaymentFlow(db),
            "personal_accident": PersonalAccidentFlow(product_catalog, db),
            "travel_insurance": TravelInsuranceFlow(product_catalog, db),
            "motor_private": MotorPrivateFlow(product_catalog, db),
            "serenicare": SerenicareFlow(product_catalog, db),
        }

    async def process(self, user_input, session_id: str, user_id: str) -> Dict:
        """Process one step in guided mode. user_input can be a string or a dict (form_data from frontend)."""

        # Get current state
        session = self.state_manager.get_session(session_id)

        if not session or not session.get("current_flow"):
            return {"error": "No active flow. Please start a flow first."}

        # Get the active flow
        flow = self.flows[session["current_flow"]]

        if session["current_flow"] == "travel_insurance":
            collected_data = session.get("collected_data", {}) or {}
            flow_version = collected_data.get("travel_flow_version")
            if flow_version != self.TRAVEL_INSURANCE_FLOW_VERSION:
                reset_data = {"travel_flow_version": self.TRAVEL_INSURANCE_FLOW_VERSION}
                self.state_manager.clear_form_draft(session_id, session["current_flow"])
                self.state_manager.update_session(session_id, {"current_step": 0, "collected_data": reset_data})
                session["current_step"] = 0
                session["collected_data"] = reset_data

        # Process current step
        result = await flow.process_step(
            user_input=user_input,
            current_step=session["current_step"],
            collected_data=session.get("collected_data", {}),
            user_id=user_id,
        )

        # Update state based on result
        if result.get("complete"):
            # Flow is complete, transition or end
            if result.get("next_flow"):
                self.state_manager.clear_form_draft(session_id, session["current_flow"])
                self.state_manager.set_flow(session_id, result["next_flow"])
                # Pass data needed by next flow (e.g. quote_id for payment)
                if result.get("collected_data"):
                    self.state_manager.update_session(session_id, {"collected_data": result["collected_data"]})
            else:
                self.state_manager.clear_form_draft(session_id, session["current_flow"])
                self.state_manager.switch_mode(session_id, "conversational")
        elif result.get("next_step") is not None:
            # Advance to next step
            self.state_manager.update_session(
                session_id, {"current_step": result["next_step"], "collected_data": result.get("collected_data", session.get("collected_data", {}))}
            )
            # Persist draft after each successful step to support resume.
            self.state_manager.save_form_draft(
                session_id,
                session["current_flow"],
                {
                    "session_id": session_id,
                    "flow": session["current_flow"],
                    "step": result.get("next_step", session.get("current_step", 0)),
                    "collected_data": result.get("collected_data", session.get("collected_data", {})),
                    "status": "in_progress",
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )

        # Refresh session so returned flow/step reflect any transitions done above.
        updated_session = self.state_manager.get_session(session_id) or session

        return {
            "mode": "guided",
            "flow": updated_session.get("current_flow", session["current_flow"]),
            "step": result.get("next_step", updated_session.get("current_step", session["current_step"])),
            "response": result.get("response"),
            "complete": result.get("complete", False),
            "data": result.get("data"),
        }

    async def start_flow(self, flow_name: str, session_id: str, user_id: str, initial_data: Dict = None) -> Dict:
        """Start a new guided flow"""

        if flow_name not in self.flows:
            return {"error": f"Unknown flow: {flow_name}"}

        # Path attribution: a guided flow is the entry point for this conversation.
        session = self.state_manager.get_session(session_id) or {}
        conversation_id = session.get("conversation_id") or session_id
        try:
            from src.chatbot.paths import record_conversation_path
            db = getattr(self.state_manager, "db", None)
            record_conversation_path(db, conversation_id, "guided_flow", "start_flow")
        except Exception:
            pass

        # Switch to guided mode
        self.state_manager.switch_mode(session_id, "guided", flow=flow_name)

        # Initialize flow
        flow = self.flows[flow_name]
        payload = dict(initial_data or {})
        if flow_name == "travel_insurance":
            payload["travel_flow_version"] = self.TRAVEL_INSURANCE_FLOW_VERSION
        result = await flow.start(user_id, payload)

        if result.get("collected_data"):
            self.state_manager.update_session(session_id, {"collected_data": result["collected_data"]})

        return {"mode": "guided", "flow": flow_name, "step": result.get("next_step", 0), "response": result.get("response"), "data": result.get("data")}
