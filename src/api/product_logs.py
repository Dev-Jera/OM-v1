"""Product logs API — tracks which products users ask about.

Called internally by the chatbot when a product is first mentioned.
Also provides list/aggregation endpoints for analytics.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# Will be set by main.py after import
db = None


class ProductLogRequest(BaseModel):
    conversation_id: str
    user_id: str
    product_name: str
    product_category: str


@router.post("/product-logs")
async def log_product(body: ProductLogRequest):
    """Log a product interest (called by the chatbot, not the user)."""
    if not body.product_name or not body.product_name.strip():
        return {"success": False, "error": "product_name is required"}

    if db is None:
        return {"success": False, "error": "Database not available"}

    try:
        log = db.log_product_interest(
            conversation_id=body.conversation_id,
            user_id=body.user_id,
            product_name=body.product_name.strip(),
            product_category=body.product_category.strip(),
        )
    except Exception:
        logger.exception("Failed to log product interest")
        return {"success": False, "error": "Failed to record product log"}

    # Push to Zoho CRM (fire-and-forget, never blocks)
    try:
        from src.integrations.zoho.product_log_push import push_product_log_to_zoho

        push_product_log_to_zoho(
            log_id=log.id,
            conversation_id=body.conversation_id,
            user_id=body.user_id,
            product_name=body.product_name.strip(),
            product_category=body.product_category.strip(),
            background=True,
        )
    except Exception:
        logger.warning("Zoho product log push failed; record saved locally", exc_info=True)

    return {
        "success": True,
        "log_id": log.id,
    }


@router.get("/product-logs")
async def list_product_logs(user_id: Optional[str] = None):
    """List product logs (admin use)."""
    if db is None:
        return {"success": False, "error": "Database not available"}

    try:
        logs = db.list_product_logs(user_id=user_id)
        return {
            "success": True,
            "product_logs": [
                {
                    "id": log.id,
                    "conversation_id": log.conversation_id,
                    "user_id": log.user_id,
                    "product_name": log.product_name,
                    "product_category": log.product_category,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                }
                for log in logs
            ],
        }
    except Exception:
        logger.exception("Failed to list product logs")
        return {"success": False, "error": "Failed to retrieve product logs"}


@router.get("/metrics/products")
async def product_popularity():
    """Return product popularity aggregated from product logs."""
    if db is None:
        return {"success": False, "error": "Database not available"}

    try:
        logs = db.list_product_logs()
        product_counts = Counter(log.product_name for log in logs)
        category_counts = Counter(log.product_category for log in logs)

        return {
            "success": True,
            "total_logs": len(logs),
            "by_product": [
                {"product_name": name, "count": count}
                for name, count in product_counts.most_common()
            ],
            "by_category": [
                {"category": cat, "count": count}
                for cat, count in category_counts.most_common()
            ],
        }
    except Exception:
        logger.exception("Failed to compute product popularity")
        return {"success": False, "error": "Failed to compute product popularity"}
