from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime
from typing import Any, Dict

from src.integrations.contracts.interfaces import PaymentRequest, PaymentResponse, PaymentStatus


class BaseMobileMoneyMock:
    def __init__(self, provider: str, webhook_secret: str | None = None) -> None:
        provider_key = (provider or "").strip().lower()
        if provider_key not in {"mtn", "airtel", "flexipay"}:
            raise ValueError("Invalid provider. Expected 'mtn', 'airtel', or 'flexipay'.")
        self.provider = provider_key
        self.webhook_secret = webhook_secret or os.getenv("MOCK_PAYMENT_WEBHOOK_SECRET", "mock-secret")

    def initiate_payment(self, request: PaymentRequest) -> PaymentResponse:
        provider_reference = f"{self.provider.upper()}-{request.reference}"
        metadata = dict(request.metadata or {})
        metadata.setdefault("provider", self.provider)
        metadata["simulate_outcome"] = (
            "failed"
            if str(metadata.get("simulate_outcome", "success")).strip().lower() == "failed"
            else "success"
        )
        return PaymentResponse(
            reference=request.reference,
            provider_reference=provider_reference,
            status=PaymentStatus.PENDING,
            amount=request.amount,
            currency=request.currency,
            message="Payment initiated and awaiting provider callback.",
            metadata=metadata,
        )

    def build_webhook_payload(self, transaction: Any) -> Dict[str, Any]:
        transaction_metadata = getattr(transaction, "transaction_metadata", None)
        if transaction_metadata is None:
            maybe_metadata = getattr(transaction, "metadata", None)
            if isinstance(maybe_metadata, dict):
                transaction_metadata = maybe_metadata
        metadata = dict(transaction_metadata or {})

        outcome = str(metadata.get("simulate_outcome", "success")).strip().lower()
        status = "SUCCESS"
        if outcome == "failed":
            status = "FAILED"

        return {
            "reference": str(getattr(transaction, "reference", "")),
            "provider": str(getattr(transaction, "provider", self.provider)),
            "provider_reference": str(getattr(transaction, "provider_reference", "")),
            "status": status,
            "amount": float(getattr(transaction, "amount", 0.0) or 0.0),
            "currency": str(getattr(transaction, "currency", "UGX")),
            "phone_number": str(getattr(transaction, "phone_number", "")),
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata,
        }

    def sign_payload(self, payload: Dict[str, Any]) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hmac.new(
            self.webhook_secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
