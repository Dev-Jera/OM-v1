"""Premium policy selector service."""

from __future__ import annotations

import os
from typing import Any, Dict

from src.integrations.clients.mocks.premium_mocks.premium import MockPremiumClient
from src.integrations.clients.real_http.premium import RealPremiumClient
from src.integrations.contracts.premium import PremiumContract


class PremiumService:
    """Select mock vs real premium client based on env policy."""

    def __init__(
        self,
        mock_client: PremiumContract | None = None,
        real_client: PremiumContract | None = None,
    ) -> None:
        self.mock_client = mock_client or MockPremiumClient()
        self.real_client = real_client or RealPremiumClient()

    async def calculate(self, product_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized_key, normalized_payload = self._normalize_payload(product_key, payload)
        return await self._select_client().calculate_premium(normalized_key, normalized_payload)

    def calculate_sync(self, product_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized_key, normalized_payload = self._normalize_payload(product_key, payload)
        return self._select_client().calculate_premium_sync(normalized_key, normalized_payload)

    @staticmethod
    def _select_mode() -> str:
        return os.getenv("PREMIUM_CLIENT_MODE", "real").strip().lower()

    def _select_client(self) -> PremiumContract:
        if self._select_mode() == "mock":
            return self.mock_client
        return self.real_client

    @staticmethod
    def _normalize_payload(product_key: str, payload: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        """Normalize common frontend payload shapes before premium calculation."""
        raw_key = str(product_key or "").strip().lower().replace("-", "_").replace(" ", "_")
        key_aliases = {
            "travel": "travel_insurance",
            "travel_insurance": "travel_insurance",
            "personal_accident": "personal_accident",
            "motor_private": "motor_private",
            "serenicare": "serenicare",
        }
        normalized_key = key_aliases.get(raw_key, raw_key)

        normalized_payload = dict(payload or {})
        data = normalized_payload.get("data")
        data_dict = data if isinstance(data, dict) else {}

        if normalized_key == "personal_accident":
            if normalized_payload.get("sum_assured") in (None, "", 0):
                cover = (
                    normalized_payload.get("coverLimitAmountUgx")
                    or data_dict.get("coverLimitAmountUgx")
                    or data_dict.get("cover_limit_ugx")
                    or data_dict.get("sum_assured")
                )
                if cover not in (None, ""):
                    try:
                        normalized_payload["sum_assured"] = int(str(cover).replace(",", "").strip())
                    except (TypeError, ValueError):
                        # Leave as-is; downstream validator/calculator will raise or compute accordingly.
                        pass

            if isinstance(data_dict.get("riskyActivities"), list) and "risky_activities" not in data_dict:
                normalized_payload["data"] = dict(data_dict)
                normalized_payload["data"]["risky_activities"] = {"selected": data_dict.get("riskyActivities", [])}

        return normalized_key, normalized_payload


premium_service = PremiumService()
