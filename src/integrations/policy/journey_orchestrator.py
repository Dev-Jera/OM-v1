"""Unified orchestration for underwriting, quotation, premium, and payment handoff.

This module provides a single integration-layer service that composes existing
underwriting, quotation, and premium services while returning payment-ready
handoff metadata for guided flows and API endpoints.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from src.integrations.clients.mocks.product_logic import get_quote_builder, normalize_product_key
from src.integrations.clients.mocks.underwriting import mock_underwriting_client
from src.integrations.config import should_use_real_integrations
from src.integrations.policy.premium import premium_service
from src.integrations.policy.quotation_service import QuotationService
from src.integrations.policy.response_wrappers import (
    normalize_quotation_response,
    normalize_underwriting_response,
)
from src.integrations.policy.underwriting_service import UnderwritingService
from src.integrations.policy.product_journeys.personal_accident import PersonalAccidentJourneyEngine
from src.integrations.policy.product_journeys.motor_private import MotorPrivateJourneyEngine
from src.integrations.policy.product_journeys.serenicare import SerenicareJourneyEngine
from src.integrations.policy.product_journeys.travel_insurance import TravelInsuranceJourneyEngine


class JourneyOrchestratorService:
    """Single service facade for quote journey operations."""

    def __init__(self) -> None:
        self._local_engines = {
            "personal_accident": PersonalAccidentJourneyEngine(),
            "motor_private": MotorPrivateJourneyEngine(),
            "serenicare": SerenicareJourneyEngine(),
            "travel_insurance": TravelInsuranceJourneyEngine(),
        }

    @staticmethod
    def _normalize_product_key(product_key: str) -> str:
        return str(product_key or "").strip().lower().replace("-", "_").replace(" ", "_")

    async def run_underwriting_and_quotation_preview(
        self,
        *,
        user_id: str,
        product_id: str,
        underwriting_data: Dict[str, Any],
        currency: str = "UGX",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run underwriting + quotation preview without persistence."""
        normalized_key = self._normalize_product_key(product_id)
        local_engine = self._local_engines.get(normalized_key)
        if local_engine is not None:
            underwriting_raw = local_engine.assess_underwriting(
                user_id=user_id,
                underwriting_data=underwriting_data,
                currency=currency,
            )
            underwriting = normalize_underwriting_response(underwriting_raw)
            decision = (underwriting.decision_status or "").strip().upper()

            if decision in {"DECLINED", "REJECTED"}:
                return {
                    "declined": True,
                    "decision_status": decision,
                    "underwriting": underwriting.model_dump(),
                    "payment": None,
                }

            quotation_raw = local_engine.generate_quotation(
                underwriting=underwriting.model_dump(),
                currency=currency,
            )
            quotation = normalize_quotation_response(
                quotation_raw,
                fallback_quote_id=underwriting.quote_id,
                fallback_currency=currency,
            )
            return {
                "declined": False,
                "decision_status": decision or "APPROVED",
                "underwriting": underwriting.model_dump(),
                "quotation": quotation.model_dump(),
                "payment": self.build_payment_handoff(quote_id=quotation.quote_id),
            }

        metadata = metadata or {}

        underwriting_payload = {
            "user_id": user_id,
            "product_id": product_id,
            "underwriting_data": underwriting_data,
            "currency": currency,
            **metadata,
        }

        if should_use_real_integrations() and os.getenv("PARTNER_UNDERWRITING_API_URL"):
            underwriting_raw = await UnderwritingService().submit_underwriting(underwriting_payload)
        else:
            mock_payload = {
                **(underwriting_data or {}),
                "user_id": user_id,
                "product_id": product_id,
                "currency": currency,
                "underwriting_data": underwriting_data,
                **metadata,
            }
            underwriting_raw = await mock_underwriting_client.submit_underwriting(mock_payload)

        underwriting = normalize_underwriting_response(underwriting_raw)
        decision = (underwriting.decision_status or "").strip().upper()

        if decision in {"DECLINED", "REJECTED"}:
            return {
                "declined": True,
                "decision_status": decision,
                "underwriting": underwriting.model_dump(),
                "payment": None,
            }

        quotation_payload: Dict[str, Any] = {
            "user_id": user_id,
            "product_id": product_id,
            "underwriting": underwriting.model_dump(),
            "currency": currency,
            **metadata,
        }

        if should_use_real_integrations() and os.getenv("PARTNER_QUOTATION_API_URL"):
            quotation_raw = await QuotationService(
                base_url=os.getenv("PARTNER_QUOTATION_API_URL", ""),
                api_key=os.getenv("PARTNER_QUOTATION_API_KEY"),
            ).get_quote(quotation_payload)
        else:
            quote_builder = get_quote_builder(normalize_product_key(product_id))
            if quote_builder:
                quotation_raw = quote_builder(underwriting_data, underwriting.model_dump())
            else:
                quotation_raw = {
                    "quote_id": underwriting.quote_id,
                    "premium": underwriting.premium,
                    "currency": underwriting.currency or currency,
                    "status": "quoted",
                    "amount": underwriting.premium,
                }

        quotation = normalize_quotation_response(
            quotation_raw,
            fallback_quote_id=underwriting.quote_id,
            fallback_currency=currency,
        )

        return {
            "declined": False,
            "decision_status": decision or "APPROVED",
            "underwriting": underwriting.model_dump(),
            "quotation": quotation.model_dump(),
            "payment": self.build_payment_handoff(quote_id=quotation.quote_id),
        }

    def calculate_product_premium(self, product_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate product premium via existing premium policy selector."""
        normalized_key = self._normalize_product_key(product_key)
        local_engine = self._local_engines.get(normalized_key)
        if local_engine is not None:
            return local_engine.calculate_premium(payload)
        return premium_service.calculate_sync(product_key, payload)

    @staticmethod
    def build_payment_handoff(*, quote_id: str, policy_or_quote_id: Optional[str] = None) -> Dict[str, Any]:
        """Build payment-ready payload consumed by PaymentFlow.start/process."""
        identifier = policy_or_quote_id or quote_id
        return {
            "policy_or_quote_id": identifier,
            "quote_id": quote_id,
            "next_flow": "payment",
        }


journey_orchestrator = JourneyOrchestratorService()
