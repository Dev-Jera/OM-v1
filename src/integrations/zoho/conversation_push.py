"""Live conversation push into Zoho CRM.

When a conversation ends, this pushes one record into the
``Mia_Conversations`` CRM module so every chat is visible in Zoho
Analytics for dashboards, trends, and product popularity reports.

Design rules (same as escalation_push / complaint_push):
- **Fire-and-forget**: runs in a background thread with full try/except.
- **Gated**: only active when ``ZOHO_CONVERSATION_PUSH_ENABLED`` is truthy.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_MODULE = "Mia_Conversations"
TRANSCRIPT_MESSAGE_LIMIT = 30
TRANSCRIPT_MAX_CHARS = 30000

# The real customer name is never sent to Zoho; only a masked placeholder, per
# the privacy requirement that the bot "strictly passes the name as {name}".
CLIENT_NAME_MASK = ":clients_name"


def _enabled() -> bool:
    return os.getenv("ZOHO_CONVERSATION_PUSH_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _build_transcript(db: Any, conversation_id: Optional[str]) -> str:
    if not db or not conversation_id or not hasattr(db, "list_messages"):
        return ""
    try:
        messages = db.list_messages(
            start=datetime(2020, 1, 1),
            end=datetime.utcnow() + timedelta(hours=1),
            conversation_id=str(conversation_id),
            limit=TRANSCRIPT_MESSAGE_LIMIT,
        )
    except Exception:
        logger.exception("Failed to load transcript for conversation %s", conversation_id)
        return ""
    lines = []
    for m in reversed(messages):
        role = str(getattr(m, "role", "") or "unknown")
        content = str(getattr(m, "content", "") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    transcript = "\n".join(lines)
    if len(transcript) > TRANSCRIPT_MAX_CHARS:
        transcript = transcript[:TRANSCRIPT_MAX_CHARS] + "\n[transcript truncated]"
    return transcript


def _resolve_outcome(db: Any, conversation_id: Optional[str]) -> str:
    """Determine the conversation outcome from events."""
    if not db or not conversation_id:
        return "unknown"
    if not hasattr(db, "list_conversation_events"):
        return "unknown"
    try:
        start = datetime.min.replace(tzinfo=None)
        end = datetime.max.replace(tzinfo=None)
        events = db.list_conversation_events(start=start, end=end)
        events = [e for e in events if getattr(e, "conversation_id", "") == conversation_id]
    except Exception:
        return "unknown"

    # Priority: bot_down > escalated > resolved > unresolved > no_verdict
    has_escalation = False
    has_completion = False
    completion_outcome = None

    for ev in events:
        ev_type = getattr(ev, "event_type", "") or ""
        payload = getattr(ev, "payload", {}) or {}
        if ev_type == "service_error":
            return "bot_down"
        if ev_type == "escalation_confirmed":
            has_escalation = True
        if ev_type == "completion_confirmed":
            has_completion = True
            completion_outcome = payload.get("outcome")

    if has_escalation:
        return "escalated"
    if has_completion and completion_outcome == "resolved":
        return "resolved"
    if has_completion and completion_outcome == "unresolved":
        return "unresolved"
    return "no_verdict"


def _resolve_csat(db: Any, conversation_id: Optional[str]) -> Optional[float]:
    """Get the CSAT rating if available."""
    if not db or not conversation_id:
        return None
    if not hasattr(db, "list_conversation_events"):
        return None
    try:
        start = datetime.min.replace(tzinfo=None)
        end = datetime.max.replace(tzinfo=None)
        events = db.list_conversation_events(start=start, end=end)
        events = [e for e in events if getattr(e, "conversation_id", "") == conversation_id]
    except Exception:
        return None
    for ev in events:
        if getattr(ev, "event_type", "") == "csat":
            rating = (getattr(ev, "payload", {}) or {}).get("rating")
            if rating is not None:
                return float(rating)
    return None


def _resolve_message_count(db: Any, conversation_id: Optional[str]) -> int:
    if not db or not conversation_id:
        return 0
    if not hasattr(db, "list_messages"):
        return 0
    try:
        messages = db.list_messages(
            start=datetime(2020, 1, 1),
            end=datetime.utcnow() + timedelta(hours=1),
            conversation_id=str(conversation_id),
            limit=500,
        )
        return len(messages)
    except Exception:
        return 0


def build_conversation_record(
    *,
    conversation_id: str,
    user_id: Optional[str],
    session_context: Optional[Dict[str, Any]],
    db: Any,
    conversation: Any = None,
) -> Dict[str, Any]:
    # Product info from session context (read before Redis deletion)
    product_topic = (session_context or {}).get("product_topic") or {}
    product_name = product_topic.get("name") or ""
    digital_flow = product_topic.get("digital_flow") or ""
    category_map = {
        "motor_private": "vehicle",
        "travel_insurance": "personal",
        "personal_accident": "personal",
        "serenicare": "personal",
    }
    product_category = category_map.get(digital_flow, "general")

    # User info from DB
    customer_name = ""
    phone = ""
    zoho_contact_id = ""
    if db is not None and user_id and hasattr(db, "get_user_by_id"):
        try:
            user = db.get_user_by_id(str(user_id))
        except Exception:
            user = None
        if user is not None:
            customer_name = str(getattr(user, "name", "") or "")
            phone = str(getattr(user, "phone_number", "") or "")
            zoho_contact_id = str(getattr(user, "zoho_contact_id", "") or "")

    # Outcome and CSAT
    outcome = _resolve_outcome(db, conversation_id)
    csat = _resolve_csat(db, conversation_id)
    message_count = _resolve_message_count(db, conversation_id)

    # Duration
    mode = "conversational"
    started_at = datetime.utcnow()
    ended_at = datetime.utcnow()
    duration_seconds = 0
    if conversation is not None:
        mode = str(getattr(conversation, "mode", "") or "conversational")
        started_at = getattr(conversation, "created_at", started_at) or started_at
        ended_at = getattr(conversation, "ended_at", ended_at) or ended_at
        if started_at and ended_at:
            duration_seconds = max(0, int((ended_at - started_at).total_seconds()))

    return {
        "Name": str(conversation_id or "conversation"),
        "Conversation_ID": str(conversation_id or ""),
        "User_ID": str(user_id or ""),
        "Customer_Name": CLIENT_NAME_MASK if customer_name else "",
        "Phone": phone,
        "Zoho_Contact_Id": zoho_contact_id,
        "Product_Name": product_name,
        "Product_Category": product_category,
        "Outcome": outcome,
        "Mode": mode,
        "CSAT": csat if csat is not None else "",
        "Message_Count": message_count,
        "Duration_Seconds": duration_seconds,
        "Started_At": started_at.strftime("%Y-%m-%dT%H:%M:%SZ") if started_at else "",
        "Ended_At": ended_at.strftime("%Y-%m-%dT%H:%M:%SZ") if ended_at else "",
        "Transcript": _build_transcript(db, conversation_id),
    }


def _push_sync(record: Dict[str, Any], module: str) -> None:
    from src.integrations.zoho.crm_writer import ZohoCRMWriter
    from src.integrations.zoho.oauth import ZohoTokenManager

    client_id = os.getenv("ZOHO_CLIENT_ID", "").strip()
    client_secret = os.getenv("ZOHO_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("ZOHO_REFRESH_TOKEN", "").strip()
    if not client_id or not client_secret or not refresh_token:
        logger.warning("Zoho conversation push skipped: missing ZOHO credentials")
        return
    token_manager = ZohoTokenManager(
        client_id,
        client_secret,
        refresh_token,
        region=os.getenv("ZOHO_REGION", "com").strip().lower(),
    )
    writer = ZohoCRMWriter(token_manager, module)
    response = writer.create([record])
    logger.info(
        "Zoho conversation push ok: conversation=%s outcome=%s response_status=%s",
        record.get("Conversation_ID"),
        record.get("Outcome"),
        (response or {}).get("status"),
    )


def push_conversation_to_zoho(
    *,
    conversation_id: str,
    user_id: Optional[str] = None,
    session_context: Optional[Dict[str, Any]] = None,
    db: Any = None,
    conversation: Any = None,
    background: bool = True,
) -> bool:
    """Push one conversation into Zoho CRM. Never raises.

    Returns True when a push was attempted (gate open + creds present).
    """
    if not _enabled():
        return False
    try:
        module = os.getenv("ZOHO_CONVERSATION_MODULE", DEFAULT_MODULE)
        record = build_conversation_record(
            conversation_id=conversation_id,
            user_id=user_id,
            session_context=session_context,
            db=db,
            conversation=conversation,
        )
    except Exception:
        logger.exception("Failed to build Zoho conversation record; request continues unaffected")
        return False

    if not background:
        try:
            _push_sync(record, module)
        except Exception:
            logger.exception("Zoho conversation push failed; request continues unaffected")
        return True

    def _worker() -> None:
        try:
            _push_sync(record, module)
        except Exception:
            logger.exception("Zoho conversation push failed; request continues unaffected")

    threading.Thread(target=_worker, daemon=True, name="zoho-conversation-push").start()
    return True
