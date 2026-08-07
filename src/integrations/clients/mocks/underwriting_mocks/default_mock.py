"""Generic underwriting mock builder used as fallback."""

from __future__ import annotations

from typing import Any, Dict


def build_default_mock(payload: Dict[str, Any], quote_id: str) -> Dict[str, Any]:
    _ = payload
    return {
        "quote_id": quote_id,
        "premium": 50000.0,
        "currency": "UGX",
        "decision_status": "approved",
        "requirements": [],
        "product_mock": "general",
        "notes": "Generic underwriting mock used. No product-specific flow matched.",
    }
