import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel
from src.chatbot.state_manager import StateManager


def _resolve_general_info_file(product: str, product_dir: Path) -> Optional[Path]:
    """Resolve the general info JSON file for a given product key."""
    normalized = product.lower().replace(" ", "-").replace("_", "-")
    if not normalized or not product_dir.exists():
        return None

    candidate_files = sorted(product_dir.glob("*.json"))

    def _load_info(path: Path) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        return data

    # 1) exact filename/display-name matches
    for path in candidate_files:
        if normalized in {
            path.stem.lower(),
            path.stem.lower().replace("-", " ").replace("_", " "),
        }:
            return path

    # 2) fuzzy match against product_id / title inside JSON
    for path in candidate_files:
        info = _load_info(path)
        pid = str(info.get("product_id") or "").lower()
        title = str(info.get("title") or "").lower()
        if pid and normalized in pid:
            return path
        if title and normalized in title:
            return path

    # 3) fallback: substring match on filename stem
    for path in candidate_files:
        if normalized in path.stem.lower():
            return path

    return None

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
async def escalate(body: EscalateRequest, request: Request = None):
    if not body.session_id:
        return {"success": False, "error": "Missing session_id"}

    # Session ownership check (defense-in-depth for frontend calls).
    # Zoho webhooks don't carry session tokens, so we only enforce when a
    # token is present.
    if request is not None:
        token = request.cookies.get("om_chat_session") or request.headers.get("X-SESSION-TOKEN")
        if token:
            session = state_manager.get_session(body.session_id) or {}
            from src.chatbot.dependencies import verify_session_capability
            if not verify_session_capability(token, body.session_id, session.get("user_id")):
                return {"success": False, "error": "Session access denied"}

    metadata = body.metadata or {}

    # If this is a non-routed general info escalation, attach full product JSON
    if body.reason == "general_info_non_routed" and body.metadata and body.metadata.get("product"):
        product_key = body.metadata["product"]
        try:
            BASE_DIR = Path(__file__).resolve().parents[1]
            PRODUCT_DIR = BASE_DIR / "general_information" / "product_json"
            product_file = _resolve_general_info_file(product_key, PRODUCT_DIR)
            if product_file and product_file.exists():
                with open(product_file, "r", encoding="utf-8") as f:
                    full_product_json = json.load(f)
                metadata["full_product_json"] = full_product_json
        except Exception:
            # Silently continue if we can't load the JSON
            pass

    # Route through EscalationService so every escalation path (endpoint,
    # button, chat trigger) also fires the Zoho handoff hook.
    from src.integrations.policy.escalation_service import EscalationService

    EscalationService(state_manager=state_manager).escalate_to_human(
        session_id=body.session_id,
        reason=body.reason or "customer_requested_agent",
        metadata=metadata,
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
async def end_escalation(body: EndEscalationRequest, request: Request = None):
    if not body.session_id:
        return {"success": False, "error": "Missing session_id"}

    # Session ownership check (defense-in-depth for frontend calls).
    if request is not None:
        token = request.cookies.get("om_chat_session") or request.headers.get("X-SESSION-TOKEN")
        if token:
            session = state_manager.get_session(body.session_id) or {}
            from src.chatbot.dependencies import verify_session_capability
            if not verify_session_capability(token, body.session_id, session.get("user_id")):
                return {"success": False, "error": "Session access denied"}

    state = state_manager.end_escalation(body.session_id)
    return {"success": True, "escalated": False, "state": state}


@router.post("/escalate/timeout")
async def escalation_timeout(body: EscalateRequest):
    """Called when Zoho operator times out (30s)"""
    if not body.session_id:
        return {"success": False, "error": "Missing session_id"}
    state_manager.mark_escalated(body.session_id, reason="operator_timeout")
    return {"success": True}


@router.post("/escalate/offline")
async def escalation_offline(body: EscalateRequest):
    """Called when no operators are online"""
    if not body.session_id:
        return {"success": False, "error": "Missing session_id"}
    state_manager.mark_escalated(body.session_id, reason="offline")
    return {"success": True}


@router.post("/escalate/invalid")
async def escalation_invalid(body: EscalateRequest):
    """Called when operator connection is invalid"""
    if not body.session_id:
        return {"success": False, "error": "Missing session_id"}
    state_manager.mark_escalated(body.session_id, reason="invalid_config")
    return {"success": True}


@router.get("/escalate/{session_id}")
async def get_escalation_state(session_id: str):
    if not session_id:
        return {"success": False, "error": "Missing session_id"}
    state = state_manager.get_escalation_state(session_id)
    return {"success": True, "state": state}


# escalation
