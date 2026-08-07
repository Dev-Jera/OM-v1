"""Personal Accident premium mock builder."""

from __future__ import annotations

from typing import Any, Dict

from src.integrations.clients.mocks.product_logic.personal_accident_insurance import build_personal_accident_premium


def build_personal_accident_premium_mock(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build Personal Accident premium payload with flow-compatible shape."""
    return build_personal_accident_premium(payload)
