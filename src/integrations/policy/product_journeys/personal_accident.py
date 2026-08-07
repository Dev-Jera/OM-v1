from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

from src.integrations.clients.mocks.product_logic.personal_accident_insurance import (
    build_personal_accident_premium,
    build_personal_accident_quote,
    build_personal_accident_underwriting,
)


class PersonalAccidentJourneyEngine:
    product_id = "personal_accident"

    def assess_underwriting(self, *, user_id: str, underwriting_data: Dict[str, Any], currency: str = "UGX") -> Dict[str, Any]:
        return build_personal_accident_underwriting(
            {**underwriting_data, "user_id": user_id, "currency": currency},
            f"UW-PA-{uuid4().hex[:10].upper()}",
        )

    def calculate_premium(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return build_personal_accident_premium(payload)

    def generate_quotation(self, *, underwriting: Dict[str, Any], currency: str = "UGX") -> Dict[str, Any]:
        return build_personal_accident_quote(underwriting.get("raw") or underwriting, underwriting)
