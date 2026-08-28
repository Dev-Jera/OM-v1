"""Complaints API - single endpoint for filing customer complaints.

Called by the Zoho SalesIQ plug when a customer clicks "File a Complaint".
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# Will be set by main.py after import
db = None


VALID_CATEGORIES = {"billing", "service", "product", "claims", "other"}


class ComplaintRequest(BaseModel):
    name: str
    email: str
    category: str
    complaint: str


@router.post("/complaints")
async def file_complaint(body: ComplaintRequest, request: Request = None):
    if not body.name or not body.name.strip():
        return {"success": False, "error": "Name is required"}
    if not body.email or not body.email.strip():
        return {"success": False, "error": "Email is required"}
    if not body.complaint or not body.complaint.strip():
        return {"success": False, "error": "Complaint text is required"}

    category = (body.category or "other").strip().lower()
    if category not in VALID_CATEGORIES:
        category = "other"

    # Resolve user_id from session cookie if available
    user_id = "anonymous"
    if request is not None:
        try:
            cookies = request.cookies or {}
            om_chat = cookies.get("om_chat_session", "")
            if om_chat:
                user_id = om_chat.split("|")[0] if "|" in om_chat else om_chat
        except Exception:
            pass

    if db is None:
        return {"success": False, "error": "Database not available"}

    try:
        complaint = db.create_complaint(
            user_id=user_id,
            name=body.name.strip(),
            email=body.email.strip(),
            category=category,
            complaint_text=body.complaint.strip(),
        )
    except Exception as exc:
        logger.exception("Failed to create complaint")
        return {"success": False, "error": "Failed to record complaint"}

    # Push to Zoho CRM (fire-and-forget, never blocks)
    try:
        from src.integrations.zoho.complaint_push import push_complaint_to_zoho

        push_complaint_to_zoho(
            complaint_id=complaint.id,
            name=body.name.strip(),
            email=body.email.strip(),
            category=category,
            complaint_text=body.complaint.strip(),
            user_id=user_id,
            background=True,
        )
    except Exception:
        logger.warning("Zoho complaint push failed; record saved locally", exc_info=True)

    logger.info(
        "Complaint filed: id=%s category=%s email=%s",
        complaint.id,
        category,
        body.email.strip(),
    )

    return {
        "success": True,
        "complaint_id": complaint.id,
        "message": "Your complaint has been recorded. Our team will review it and get back to you.",
    }


@router.get("/complaints")
async def list_complaints(user_id: Optional[str] = None):
    """List complaints (admin use)."""
    if db is None:
        return {"success": False, "error": "Database not available"}

    try:
        complaints = db.list_complaints(user_id=user_id)
        return {
            "success": True,
            "complaints": [
                {
                    "id": c.id,
                    "user_id": c.user_id,
                    "name": c.name,
                    "email": c.email,
                    "category": c.category,
                    "complaint": c.complaint,
                    "status": c.status,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in complaints
            ],
        }
    except Exception as exc:
        logger.exception("Failed to list complaints")
        return {"success": False, "error": "Failed to retrieve complaints"}


@router.get("/complaints/{complaint_id}")
async def get_complaint(complaint_id: str):
    """Get a single complaint."""
    if db is None:
        return {"success": False, "error": "Database not available"}

    complaint = db.get_complaint(complaint_id)
    if not complaint:
        return {"success": False, "error": "Complaint not found"}

    return {
        "success": True,
        "complaint": {
            "id": complaint.id,
            "user_id": complaint.user_id,
            "name": complaint.name,
            "email": complaint.email,
            "category": complaint.category,
            "complaint": complaint.complaint,
            "status": complaint.status,
            "created_at": complaint.created_at.isoformat() if complaint.created_at else None,
        },
    }
