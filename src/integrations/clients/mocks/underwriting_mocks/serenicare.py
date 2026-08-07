"""Serenicare-specific underwriting mock builder."""

from __future__ import annotations

from typing import Any, Dict

from src.integrations.clients.mocks.product_logic.serenicare_insurance import build_serenicare_underwriting


def build_serenicare_mock(payload: Dict[str, Any], quote_id: str) -> Dict[str, Any]:
    return build_serenicare_underwriting(payload, quote_id)
