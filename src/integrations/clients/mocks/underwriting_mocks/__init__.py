"""Registry for product-specific underwriting mock builders."""

from __future__ import annotations

from typing import Any, Callable, Dict

from .default_mock import build_default_mock
from .personal_accident import build_personal_accident_mock
from .serenicare import build_serenicare_mock
from src.integrations.clients.mocks.product_logic.motor_private import build_motor_private_underwriting
from src.integrations.clients.mocks.product_logic.travel_insurance_service import build_travel_insurance_underwriting

MockBuilder = Callable[[Dict[str, Any], str], Dict[str, Any]]

_REGISTRY: Dict[str, MockBuilder] = {
    "serenicare": build_serenicare_mock,
    "personal_accident": build_personal_accident_mock,
    "travel_insurance": build_travel_insurance_underwriting,
    "motor_private": build_motor_private_underwriting,
    "general": build_default_mock,
}


def get_product_mock_builder(product_key: str) -> MockBuilder:
    """Return product-specific mock builder with safe fallback."""
    return _REGISTRY.get(product_key, build_default_mock)
