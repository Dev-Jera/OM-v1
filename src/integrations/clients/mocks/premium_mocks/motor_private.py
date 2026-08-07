"""Motor Private premium mock builder."""

from __future__ import annotations

from typing import Any, Dict

from src.integrations.clients.mocks.product_logic.motor_private import build_motor_private_premium


def build_motor_private_premium_mock(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build Motor Private premium payload with flow-compatible shape."""
    return build_motor_private_premium(payload)
