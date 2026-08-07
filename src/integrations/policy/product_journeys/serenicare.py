from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

from src.integrations.clients.mocks.product_logic.serenicare_insurance import (
    build_serenicare_premium,
    build_serenicare_quote,
    build_serenicare_underwriting,
)


class SerenicareJourneyEngine:
    product_id = "serenicare"

    def assess_underwriting(self, *, user_id: str, underwriting_data: Dict[str, Any], currency: str = "UGX") -> Dict[str, Any]:
        return build_serenicare_underwriting(
            {**underwriting_data, "user_id": user_id, "currency": currency},
            f"UW-SC-{uuid4().hex[:10].upper()}",
        )

    def calculate_premium(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return build_serenicare_premium(payload)

    def generate_quotation(self, *, underwriting: Dict[str, Any], currency: str = "UGX") -> Dict[str, Any]:
        return build_serenicare_quote(underwriting.get("raw") or underwriting, underwriting)
