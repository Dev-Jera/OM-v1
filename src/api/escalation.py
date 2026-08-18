from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel
from src.chatbot.state_manager import StateManager

router = APIRouter()


# Will be set by main.py after import
state_manager: StateManager = None


class EscalateRequest(BaseModel):
    session_id: str
    reason: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class AgentJoinRequest(BaseModel):
    session_id: str
    agent_id: str


class EndEscalationRequest(BaseModel):
    session_id: str


@router.post("/escalate")
async def escalate(body: EscalateRequest):
    if not body.session_id:
        return {"success": False, "error": "Missing session_id"}
    # Route through EscalationService so every escalation path (endpoint,
    # button, chat trigger) also fires the Zoho handoff hook.
    from src.integrations.policy.escalation_service import EscalationService

    EscalationService(state_manager=state_manager).escalate_to_human(
        session_id=body.session_id,
        reason=body.reason or "customer_requested_agent",
        metadata=body.metadata or {},
    )
    state = state_manager.get_escalation_state(body.session_id)
    # Path attribution: a direct /escalate call means the user chose a human agent.
    session = state_manager.get_session(body.session_id) or {}
    conversation_id = session.get("conversation_id") or body.session_id
    try:
        from src.chatbot.paths import record_conversation_path
        record_conversation_path(
            getattr(state_manager, "db", None), conversation_id, "direct_agent", "escalate_endpoint"
        )
    except Exception:
        pass
    # Emit the same escalation_confirmed event the outcome model keys on, so
    # direct escalations show up in resolution/impact metrics like chat-flow
    # escalations do.
    try:
        db = getattr(state_manager, "db", None)
        if db is not None and hasattr(db, "add_conversation_event"):
            db.add_conversation_event(
                conversation_id=conversation_id,
                event_type="escalation_confirmed",
                payload={"source": "user", "reason": body.reason or "customer_requested_agent"},
            )
    except Exception:
        pass
    return {"success": True, "escalated": True, "state": state}


@router.post("/escalate/agent-join")
async def agent_join(body: AgentJoinRequest):
    if not body.session_id or not body.agent_id:
        return {"success": False, "error": "Missing session_id or agent_id"}
    state = state_manager.mark_agent_joined(body.session_id, body.agent_id)
    return {"success": True, "escalated": True, "state": state}


@router.post("/escalate/end")
async def end_escalation(body: EndEscalationRequest):
    if not body.session_id:
        return {"success": False, "error": "Missing session_id"}
    state = state_manager.end_escalation(body.session_id)
    return {"success": True, "escalated": False, "state": state}


@router.get("/escalate/{session_id}")
async def get_escalation_state(session_id: str):
    if not session_id:
        return {"success": False, "error": "Missing session_id"}
    state = state_manager.get_escalation_state(session_id)
    return {"success": True, "state": state}


# escalation
