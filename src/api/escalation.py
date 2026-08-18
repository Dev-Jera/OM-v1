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
    state = state_manager.mark_escalated(body.session_id, reason=body.reason, metadata=body.metadata or {})
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
