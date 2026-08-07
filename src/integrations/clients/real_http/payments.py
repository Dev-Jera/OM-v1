"""
Real Payments HTTP Client.

Used when partner payment gateway credentials are configured.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from src.integrations.contracts.interfaces import PaymentRequest, PaymentResponse
from src.integrations.policy.response_wrappers import normalize_payment_gateway_response


class RealPaymentsClient:
    def __init__(
        self,
        provider: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        initiate_path: Optional[str] = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.provider = provider
        self.base_url = (base_url or os.getenv("PARTNER_PAYMENT_API_URL", "")).rstrip("/")
        self.api_key = api_key or os.getenv("PARTNER_PAYMENT_API_KEY", "")
        self.initiate_path = initiate_path or os.getenv("PARTNER_PAYMENT_INITIATE_PATH", "/payments/initiate")
        self.timeout_seconds = timeout_seconds

    async def initiate_payment(self, request: PaymentRequest) -> PaymentResponse:
        if not self.base_url:
            raise ValueError("PARTNER_PAYMENT_API_URL is not configured.")

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: Dict[str, Any] = {
            "provider": self.provider,
            "reference": request.reference,
            "phone_number": request.phone_number,
            "amount": request.amount,
            "currency": request.currency,
            "description": request.description,
            "metadata": request.metadata,
        }

        url = f"{self.base_url}{self.initiate_path}"
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json() if response.content else {}

        normalized = normalize_payment_gateway_response(
            data,
            fallback_reference=request.reference,
            fallback_amount=request.amount,
            fallback_currency=request.currency,
        )

        return PaymentResponse(
            reference=normalized.reference,
            provider_reference=normalized.provider_reference,
            status=normalized.status,
            amount=normalized.amount,
            currency=normalized.currency,
            message=normalized.message,
            metadata={
                "gateway_raw": normalized.raw,
                "payee_name": (request.metadata or {}).get("payee_name"),
            },
        )
