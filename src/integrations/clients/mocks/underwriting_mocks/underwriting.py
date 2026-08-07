"""Mock underwriting client with per-product handlers.

This client routes underwriting requests to product-specific mock builders and
persists each mock interaction under the project-level ``underwriting_mocks``
folder, grouped by product.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from src.integrations.contracts.underwriting import UnderwritingContract

from . import get_product_mock_builder
from src.integrations.clients.mocks.product_logic import normalize_product_key

logger = logging.getLogger(__name__)


class MockUnderwritingClient:
    """Mock underwriting client that generates product-aware quote responses."""

    def __init__(self, output_root: Path | None = None) -> None:
        self.output_root = output_root or self._default_output_root()
        self.output_root.mkdir(parents=True, exist_ok=True)

    async def create_quote(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a mock underwriting quote for the provided payload."""
        return self._build_and_persist(payload)

    async def submit_underwriting(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Alias used by service-style integrations."""
        return self._build_and_persist(payload)

    def _build_and_persist(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        product_key = self._detect_product(payload)
        quote_id = self._generate_quote_id(product_key)

        mock_builder = get_product_mock_builder(product_key)
        mock_response = mock_builder(payload, quote_id)

        contract = UnderwritingContract(
            quote_id=mock_response["quote_id"],
            premium=float(mock_response["premium"]),
            currency=str(mock_response.get("currency", "UGX")),
            decision_status=str(mock_response["decision_status"]),
            requirements=list(mock_response.get("requirements", [])),
        )

        response: Dict[str, Any] = contract.model_dump()
        response.update({
            key: value
            for key, value in mock_response.items()
            if key not in response
        })

        output_path = self._write_mock_output(product_key, payload, response)
        response["mock_output_path"] = str(output_path)
        return response

    def _write_mock_output(self, product_key: str, payload: Dict[str, Any], response: Dict[str, Any]) -> Path:
        product_dir = self.output_root / product_key
        product_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_quote_id = str(response.get("quote_id", "unknown")).replace("/", "_")
        file_path = product_dir / f"{timestamp}_{safe_quote_id}.json"

        output_document = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "product_id": product_key,
            "input": payload,
            "output": response,
        }

        try:
            file_path.write_text(json.dumps(output_document, indent=2, default=str), encoding="utf-8")
        except Exception:
            logger.exception("Failed to write underwriting mock output file: %s", file_path)

        return file_path

    @staticmethod
    def _default_output_root() -> Path:
        return Path(__file__).resolve().parents[5] / "underwriting_mocks"

    @staticmethod
    def _generate_quote_id(product_key: str) -> str:
        short_product = product_key[:3].upper()
        return f"UW-MOCK-{short_product}-{uuid4().hex[:8].upper()}"

    @staticmethod
    def _detect_product(payload: Dict[str, Any]) -> str:
        nested_underwriting = payload.get("underwriting_data")
        candidates = [
            payload.get("product_id"),
            payload.get("product"),
            payload.get("flow_type"),
            nested_underwriting.get("product_id") if isinstance(nested_underwriting, dict) else None,
        ]

        for candidate in candidates:
            if not candidate:
                continue
            normalized = normalize_product_key(str(candidate))
            if normalized in {"serenicare", "personal_accident", "travel_insurance", "motor_private"}:
                return normalized

        if "plan_option" in payload and "medical_conditions" in payload:
            return "serenicare"
        if "cover_limit_ugx" in payload or "risky_activities" in payload:
            return "personal_accident"
        if "travelStartDate" in payload or "travel_party_and_trip" in payload or "travellers" in payload:
            return "travel_insurance"
        if "vehicle_value_ugx" in payload or "carValue" in payload or "car_usage_region" in payload:
            return "motor_private"

        return "general"


mock_underwriting_client = MockUnderwritingClient()
