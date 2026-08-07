"""Shared quote generation and PDF registration helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.integrations.clients.mocks.product_logic.motor_private import (
    build_motor_private_quotation,
    generate_motor_private_quote_pdf,
)
from src.integrations.clients.mocks.product_logic.personal_accident_insurance import PersonalAccidentPremiumService
from src.integrations.clients.mocks.product_logic.serenicare_insurance import SerenicarePremuimService
from src.integrations.clients.mocks.product_logic.travel_insurance_service import TravelInsurancePremiumService
from src.integrations.quote_downloads import register_quote_pdf

_pa_service = PersonalAccidentPremiumService()
_travel_service = TravelInsurancePremiumService()
_serenicare_service = SerenicarePremuimService()


_QUOTATION_BUILDERS = {
    "motor_private": build_motor_private_quotation,
    "personal_accident": _pa_service.build_quotation_sync,
    "travel_insurance": _travel_service.build_quotation_sync,
    "serenicare": _serenicare_service.build_quotation_sync,
}


def _normalize_product_key(product_id: str) -> str:
    return str(product_id or "").strip().lower().replace("-", "_")


def build_product_quotation(
    product_id: str,
    flow_data: Dict[str, Any],
    quote_id: Optional[str] = None,
) -> Dict[str, Any]:
    product_key = _normalize_product_key(product_id)
    builder = _QUOTATION_BUILDERS.get(product_key)
    if builder:
        return builder(flow_data, quote_id)
    raise ValueError(f"Unsupported product for quote generation: {product_id}")


def generate_product_quote_pdf(
    product_id: str,
    flow_data: Dict[str, Any],
    quote_id: Optional[str] = None,
    quotation: Optional[Dict[str, Any]] = None,
) -> bytes:
    product_key = _normalize_product_key(product_id)
    if product_key == "motor_private":
        quote_payload = quotation or build_motor_private_quotation(flow_data, quote_id)
        return generate_motor_private_quote_pdf(quote_payload)
    service_map = {
        "personal_accident": _pa_service,
        "travel_insurance": _travel_service,
        "serenicare": _serenicare_service,
    }
    service = service_map.get(product_key)
    if service:
        return service.generate_pdf_sync(flow_data, quote_id)
    raise ValueError(f"Unsupported product for PDF generation: {product_id}")


def generate_and_register_quote_pdf(
    product_id: str,
    flow_data: Dict[str, Any],
    *,
    quote_id: Optional[str] = None,
    product_name: Optional[str] = None,
) -> Dict[str, Any]:
    quotation = build_product_quotation(product_id, flow_data, quote_id)
    resolved_quote_id = str(quote_id or quotation.get("quote_number") or "").strip()
    if not resolved_quote_id:
        return {
            "quote_id": "",
            "download_url": "",
            "quotation": quotation,
        }

    pdf_bytes = generate_product_quote_pdf(
        product_id,
        flow_data,
        quote_id=resolved_quote_id,
        quotation=quotation,
    )
    metadata = {"product_name": product_name or str(quotation.get("product") or product_id)}
    download_url = register_quote_pdf(resolved_quote_id, pdf_bytes, metadata=metadata)
    return {
        "quote_id": resolved_quote_id,
        "download_url": download_url,
        "quotation": quotation,
    }
