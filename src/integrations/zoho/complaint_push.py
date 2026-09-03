"""Complaint push into Zoho CRM.

When a customer files a complaint, this pushes one record into the
``Mia_Complaint`` CRM module so the support team is notified.

Design rules (same as escalation_push):
- **Fire-and-forget**: runs in a background thread with full try/except.
- **Gated**: only active when ``ZOHO_COMPLAINT_PUSH_ENABLED`` is truthy.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_MODULE = "Mia_Complaint"


def _enabled() -> bool:
    return os.getenv("ZOHO_COMPLAINT_PUSH_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def build_complaint_record(
    *,
    complaint_id: str,
    name: str,
    email: str,
    category: str,
    complaint_text: str,
    user_id: str,
) -> Dict[str, Any]:
    return {
        "Name": str(complaint_id or "complaint"),
        "Customer_Name": str(name or ""),
        "Email": str(email or ""),
        "Category": str(category or "Other"),
        "Complaint": str(complaint_text or "")[:5000],
        "Status": "Submitted",
        "Submitted_At": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _push_sync(record: Dict[str, Any], module: str) -> None:
    from src.integrations.zoho.crm_writer import ZohoCRMWriter
    from src.integrations.zoho.oauth import ZohoTokenManager

    client_id = os.getenv("ZOHO_CLIENT_ID", "").strip()
    client_secret = os.getenv("ZOHO_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("ZOHO_REFRESH_TOKEN", "").strip()
    if not client_id or not client_secret or not refresh_token:
        logger.warning("Zoho complaint push skipped: missing ZOHO credentials")
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
        "Zoho complaint push ok: complaint_id=%s response_status=%s",
        record.get("Name"),
        (response or {}).get("status"),
    )


def push_complaint_to_zoho(
    *,
    complaint_id: str,
    name: str,
    email: str,
    category: str,
    complaint_text: str,
    user_id: str,
    background: bool = True,
) -> bool:
    """Push one complaint into Zoho CRM. Never raises.

    Returns True when a push was attempted (gate open + creds present).
    """
    if not _enabled():
        return False
    try:
        module = os.getenv("ZOHO_COMPLAINT_MODULE", DEFAULT_MODULE)
        record = build_complaint_record(
            complaint_id=complaint_id,
            name=name,
            email=email,
            category=category,
            complaint_text=complaint_text,
            user_id=user_id,
        )
    except Exception:
        logger.exception("Failed to build Zoho complaint record; request continues unaffected")
        return False

    if not background:
        try:
            _push_sync(record, module)
        except Exception:
            logger.exception("Zoho complaint push failed; request continues unaffected")
        return True

    def _worker() -> None:
        try:
            _push_sync(record, module)
        except Exception:
            logger.exception("Zoho complaint push failed; request continues unaffected")

    threading.Thread(target=_worker, daemon=True, name="zoho-complaint-push").start()
    return True
