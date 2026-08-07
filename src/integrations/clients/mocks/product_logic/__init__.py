"""Unified local product logic for underwriting, premium, and quotation mocks."""

from __future__ import annotations

from typing import Any, Callable, Dict

from .motor_private import (
    build_motor_private_premium,
    build_motor_private_quote,
    build_motor_private_underwriting,
)
from .personal_accident_insurance import (
    build_personal_accident_premium,
    build_personal_accident_quote,
    build_personal_accident_underwriting,
)
from .serenicare_insurance import (
    build_serenicare_premium,
    build_serenicare_quote,
    build_serenicare_underwriting,
)
from .travel_insurance_service import (
    build_travel_insurance_premium,
    build_travel_insurance_quote,
    build_travel_insurance_underwriting,
)

UnderwritingBuilder = Callable[[Dict[str, Any], str], Dict[str, Any]]
PremiumBuilder = Callable[[Dict[str, Any]], Dict[str, Any]]
QuoteBuilder = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]

_ALIASES = {
    "travel": "travel_insurance",
    "travel_insurance": "travel_insurance",
    "personal_accident": "personal_accident",
    "motor_private": "motor_private",
    "serenicare": "serenicare",
}

_UNDERWRITING_BUILDERS: Dict[str, UnderwritingBuilder] = {
    "travel_insurance": build_travel_insurance_underwriting,
    "personal_accident": build_personal_accident_underwriting,
    "motor_private": build_motor_private_underwriting,
    "serenicare": build_serenicare_underwriting,
}

_PREMIUM_BUILDERS: Dict[str, PremiumBuilder] = {
    "travel_insurance": build_travel_insurance_premium,
    "personal_accident": build_personal_accident_premium,
    "motor_private": build_motor_private_premium,
    "serenicare": build_serenicare_premium,
}

_QUOTE_BUILDERS: Dict[str, QuoteBuilder] = {
    "travel_insurance": build_travel_insurance_quote,
    "personal_accident": build_personal_accident_quote,
    "motor_private": build_motor_private_quote,
    "serenicare": build_serenicare_quote,
}


def normalize_product_key(product_key: str) -> str:
    normalized = str(product_key or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _ALIASES.get(normalized, normalized)


def get_underwriting_builder(product_key: str) -> UnderwritingBuilder | None:
    return _UNDERWRITING_BUILDERS.get(normalize_product_key(product_key))


def get_premium_builder(product_key: str) -> PremiumBuilder | None:
    return _PREMIUM_BUILDERS.get(normalize_product_key(product_key))


def get_quote_builder(product_key: str) -> QuoteBuilder | None:
    return _QUOTE_BUILDERS.get(normalize_product_key(product_key))
