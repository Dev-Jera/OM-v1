"""Personal Accident-specific underwriting mock builder."""

from __future__ import annotations

from typing import Any, Dict

from src.integrations.clients.mocks.product_logic.personal_accident_insurance import build_personal_accident_underwriting


def build_personal_accident_mock(payload: Dict[str, Any], quote_id: str) -> Dict[str, Any]:
    return build_personal_accident_underwriting(payload, quote_id)
