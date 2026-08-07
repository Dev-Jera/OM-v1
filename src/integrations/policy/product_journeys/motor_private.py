from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

from src.integrations.clients.mocks.premium_mocks.motor_private import (
    build_motor_private_premium_mock,
)
from src.integrations.clients.mocks.product_logic.motor_private import (
    build_motor_private_quote,
    build_motor_private_underwriting,
)


class MotorPrivateJourneyEngine:
    product_id = "motor_private"

    def assess_underwriting(self, *, user_id: str, underwriting_data: Dict[str, Any], currency: str = "UGX") -> Dict[str, Any]:
        return build_motor_private_underwriting(
            {**underwriting_data, "user_id": user_id, "currency": currency},
            f"UW-MP-{uuid4().hex[:10].upper()}",
        )

    def calculate_premium(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return build_motor_private_premium_mock(payload)

    def generate_quotation(self, *, underwriting: Dict[str, Any], currency: str = "UGX") -> Dict[str, Any]:
        return build_motor_private_quote(underwriting.get("raw") or underwriting, underwriting)
