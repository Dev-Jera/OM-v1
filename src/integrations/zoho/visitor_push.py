"""Visitor identity push into Zoho CRM.

Whenever the bot captures a visitor's identity (name + email, and phone when
available) through the chat identity flow or the /session/identify endpoint,
this pushes one record into the ``MiaVisitor`` CRM module so every person who
interacts with the bot is visible in Zoho as a trackable visitor/lead.

Privacy rules:
- The visitor's real name is NEVER sent to Zoho. Only the masked placeholder
  ``:clients_name`` is stored in the ``Name`` field, per the user's requirement
  that the bot "strictly passes the name as {name}". The real name stays only
  in the bot's private Postgres user record.
- Email is stored as the dedupe/match key (the same email = the same visitor).
- The push is search-first upsert keyed on Email, so a returning visitor
  updates a single record instead of creating duplicates.

Design rules (same as escalation_push / conversation_push):
- **Fire-and-forget**: runs in a background thread with full try/except.
  A Zoho outage must never break the chat or the identity capture.
- **Gated**: only active when ``ZOHO_VISITOR_PUSH_ENABLED`` is truthy.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_MODULE = "MiaVisitor"

# The masked placeholder used in Zoho instead of a real personal name.
VISITOR_NAME_MASK = ":clients_name"


def _enabled() -> bool:
    return os.getenv("ZOHO_VISITOR_PUSH_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _module() -> str:
    return os.getenv("ZOHO_VISITOR_MODULE", DEFAULT_MODULE).strip() or DEFAULT_MODULE


def build_visitor_record(
    *,
    user_id: str,
    email: Optional[str],
    phone: Optional[str] = None,
    name: Optional[str] = None,
    source: str = "chat",
    db: Any = None,
    conversation_count: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Build the ``MiaVisitor`` record for the identity push.

    The real ``name`` (if provided) is intentionally NOT stored in the record;
    only the masked placeholder is used. Email is the dedupe key. Anonymous
    visitors (no email and no phone) are still recorded so visitor volume shows
    up in dashboards; they simply use the ``create`` path since there is no key.
    """
    email = (email or "").strip().lower() or None
    phone = (phone or "").strip() or None

    if not email and db is not None and user_id and hasattr(db, "get_user_by_id"):
        try:
            user = db.get_user_by_id(str(user_id))
        except Exception:
            user = None
        if user is not None:
            if not email:
                email = (getattr(user, "email", "") or "").strip().lower() or None
            if not phone:
                phone = (getattr(user, "phone_number", "") or "").strip() or None

    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    record: Dict[str, Any] = {
        # Always masked; the real name is never pushed to Zoho.
        "Name": build_visitor_name(email or phone or user_id),
        "Email": email or "",
        "Phone": phone or "",
        "User_ID": str(user_id or ""),
        "Source": source,
        "First_Seen_At": now,
        "Last_Seen_At": now,
        "Conversation_Count": int(conversation_count or 0),
    }

    return record


def build_visitor_name(key: str) -> str:
    """Return the masked, stable ``Name`` value for the visitor record.

    Always the masked placeholder; the ``key`` is used only to derive a stable
    suffix so the same visitor keeps the same Name across calls (needed so the
    search-first upsert keyed on Email also holds on Name without duplicating).
    """
    stable = abs(hash((key or "").lower())) % 100000
    return f"{VISITOR_NAME_MASK} {stable}"


def _push_sync(record: Dict[str, Any], module: str) -> None:
    from src.integrations.zoho.crm_writer import ZohoCRMWriter
    from src.integrations.zoho.oauth import ZohoTokenManager

    client_id = os.getenv("ZOHO_CLIENT_ID", "").strip()
    client_secret = os.getenv("ZOHO_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("ZOHO_REFRESH_TOKEN", "").strip()
    if not client_id or not client_secret or not refresh_token:
        logger.warning("Zoho visitor push skipped: missing ZOHO credentials")
        return
    token_manager = ZohoTokenManager(
        client_id,
        client_secret,
        refresh_token,
        region=os.getenv("ZOHO_REGION", "com").strip().lower(),
    )
    writer = ZohoCRMWriter(token_manager, module)
    if record.get("Email"):
        # Search-first upsert keyed on Email so a returning visitor updates one
        # record instead of creating a duplicate each chat.
        response = writer.upsert([record], ["Email"])
    else:
        response = writer.create([record])
    logger.info(
        "Zoho visitor push ok: user=%s email=%s response_status=%s",
        record.get("User_ID"),
        record.get("Email"),
        (response or {}).get("status"),
    )


def push_visitor_to_zoho(
    *,
    user_id: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    name: Optional[str] = None,
    source: str = "chat",
    db: Any = None,
    conversation_count: Optional[int] = None,
    background: bool = True,
) -> bool:
    """Push one visitor identity record into Zoho ``MiaVisitor``. Never raises.

    Returns True when a push was attempted (gate open + creds present).
    Anonymous visitors (no email/phone) are recorded too.
    """
    if not _enabled():
        return False
    try:
        record = build_visitor_record(
            user_id=user_id,
            email=email,
            phone=phone,
            name=name,
            source=source,
            db=db,
            conversation_count=conversation_count,
        )
    except Exception:
        logger.exception("Failed to build Zoho visitor record; chat continues unaffected")
        return False
    if record is None:
        return False

    module = _module()

    if not background:
        try:
            _push_sync(record, module)
        except Exception:
            logger.exception("Zoho visitor push failed; chat continues unaffected")
        return True

    def _worker() -> None:
        try:
            _push_sync(record, module)
        except Exception:
            logger.exception("Zoho visitor push failed; chat continues unaffected")

    threading.Thread(target=_worker, daemon=True, name="zoho-visitor-push").start()
    return True
