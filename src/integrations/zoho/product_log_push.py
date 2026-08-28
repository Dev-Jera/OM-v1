"""Product log push into Zoho CRM.

When a product interest is logged, this pushes one record into the
``Mia_Product_Logs`` CRM module so the team can track popular products.

Design rules (same as escalation_push / complaint_push):
- **Fire-and-forget**: runs in a background thread with full try/except.
- **Gated**: only active when ``ZOHO_PRODUCT_LOG_PUSH_ENABLED`` is truthy.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger(__name__)

DEFAULT_MODULE = "Mia_Product_Logs"


def _enabled() -> bool:
    return os.getenv("ZOHO_PRODUCT_LOG_PUSH_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def build_product_log_record(
    *,
    log_id: str,
    conversation_id: str,
    user_id: str,
    product_name: str,
    product_category: str,
) -> Dict[str, Any]:
    return {
        "Name": str(log_id or "log"),
        "Conversation_ID": str(conversation_id or ""),
        "User_ID": str(user_id or ""),
        "Product_Name": str(product_name or ""),
        "Product_Category": str(product_category or ""),
        "Logged_At": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _push_sync(record: Dict[str, Any], module: str) -> None:
    from src.integrations.zoho.crm_writer import ZohoCRMWriter
    from src.integrations.zoho.oauth import ZohoTokenManager

    client_id = os.getenv("ZOHO_CLIENT_ID", "").strip()
    client_secret = os.getenv("ZOHO_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("ZOHO_REFRESH_TOKEN", "").strip()
    if not client_id or not client_secret or not refresh_token:
        logger.warning("Zoho product log push skipped: missing ZOHO credentials")
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
        "Zoho product log push ok: log_id=%s response_status=%s",
        record.get("Name"),
        (response or {}).get("status"),
    )


def push_product_log_to_zoho(
    *,
    log_id: str,
    conversation_id: str,
    user_id: str,
    product_name: str,
    product_category: str,
    background: bool = True,
) -> bool:
    """Push one product log into Zoho CRM. Never raises.

    Returns True when a push was attempted (gate open + creds present).
    """
    if not _enabled():
        return False
    try:
        module = os.getenv("ZOHO_PRODUCT_LOG_MODULE", DEFAULT_MODULE)
        record = build_product_log_record(
            log_id=log_id,
            conversation_id=conversation_id,
            user_id=user_id,
            product_name=product_name,
            product_category=product_category,
        )
    except Exception:
        logger.exception("Failed to build Zoho product log record; request continues unaffected")
        return False

    if not background:
        try:
            _push_sync(record, module)
        except Exception:
            logger.exception("Zoho product log push failed; request continues unaffected")
        return True

    def _worker() -> None:
        try:
            _push_sync(record, module)
        except Exception:
            logger.exception("Zoho product log push failed; request continues unaffected")

    threading.Thread(target=_worker, daemon=True, name="zoho-product-log-push").start()
    return True
