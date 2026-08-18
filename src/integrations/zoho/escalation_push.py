"""Escalation handoff into Zoho CRM.

When the bot escalates a conversation, this pushes one record into the
``Mia_Escalations`` CRM module (reason, customer details, chat transcript)
so Zoho-side agents are notified and take over — no one has to watch our
admin dashboard.

Design rules:
- **Fire-and-forget**: runs in a background thread with full try/except.
  A Zoho outage must never break the chat or the escalation itself.
- **Gated**: only active when ``ZOHO_ESCALATION_PUSH_ENABLED`` is truthy.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_MODULE = "Mia_Escalations"
TRANSCRIPT_MESSAGE_LIMIT = 30
TRANSCRIPT_MAX_CHARS = 30000


def _enabled() -> bool:
    return os.getenv("ZOHO_ESCALATION_PUSH_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


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
    for m in reversed(messages):  # oldest first
        role = str(getattr(m, "role", "") or "unknown")
        content = str(getattr(m, "content", "") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    transcript = "\n".join(lines)
    if len(transcript) > TRANSCRIPT_MAX_CHARS:
        transcript = transcript[:TRANSCRIPT_MAX_CHARS] + "\n[transcript truncated]"
    return transcript


def build_escalation_record(
    *,
    session_id: str,
    reason: str,
    user_id: Optional[str],
    metadata: Optional[Dict[str, Any]],
    db: Any,
) -> Dict[str, Any]:
    metadata = metadata or {}
    conversation_id = str(metadata.get("conversation_id") or session_id or "")

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

    return {
        "Escalated_At": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Conversation_ID": conversation_id,
        "Session_ID": str(session_id or ""),
        "Reason": str(reason or "")[:255],
        "Customer_Name": customer_name,
        "Phone": phone,
        "Zoho_Contact_Id": zoho_contact_id,
        "Transcript": _build_transcript(db, conversation_id or None),
        "Status": "New",
    }


def _push_sync(record: Dict[str, Any], module: str) -> None:
    from src.integrations.zoho.crm_writer import ZohoCRMWriter
    from src.integrations.zoho.oauth import ZohoTokenManager

    client_id = os.getenv("ZOHO_CLIENT_ID", "").strip()
    client_secret = os.getenv("ZOHO_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("ZOHO_REFRESH_TOKEN", "").strip()
    if not client_id or not client_secret or not refresh_token:
        logger.warning("Zoho escalation push skipped: missing ZOHO credentials")
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
        "Zoho escalation push ok: session=%s conversation=%s response_status=%s",
        record.get("Session_ID"),
        record.get("Conversation_ID"),
        (response or {}).get("status"),
    )


def push_escalation_to_zoho(
    *,
    session_id: str,
    reason: str,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    db: Any = None,
    background: bool = True,
) -> bool:
    """Push one escalation into Zoho CRM. Never raises.

    Returns True when a push was attempted (gate open + creds present).
    """
    if not _enabled():
        return False
    try:
        module = os.getenv("ZOHO_ESCALATION_MODULE", DEFAULT_MODULE)
        record = build_escalation_record(
            session_id=session_id,
            reason=reason,
            user_id=user_id,
            metadata=metadata,
            db=db,
        )
    except Exception:
        logger.exception("Failed to build Zoho escalation record; chat continues unaffected")
        return False

    if not background:
        try:
            _push_sync(record, module)
        except Exception:
            logger.exception("Zoho escalation push failed; chat continues unaffected")
        return True

    def _worker() -> None:
        try:
            _push_sync(record, module)
        except Exception:
            logger.exception("Zoho escalation push failed; chat continues unaffected")

    threading.Thread(target=_worker, daemon=True, name="zoho-escalation-push").start()
    return True
