"""
Underwriting Service for Partner API Integration

This module provides functions to interact with external partner underwriting APIs.
Includes:
- Config management (env vars)
- Error handling & logging
- Response normalization
- Security best practices
"""

import os
import httpx
import logging
from typing import Dict, Any, Optional
from src.integrations.contracts.underwriting import UnderwritingContract

logger = logging.getLogger(__name__)


class UnderwritingService:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        # Config management: load from env if not provided
        self.base_url = base_url or os.getenv("PARTNER_UNDERWRITING_API_URL", "")
        self.api_key = api_key or os.getenv("PARTNER_UNDERWRITING_API_KEY", "")
        if not self.base_url:
            logger.warning("Partner underwriting API URL is not set.")

    async def submit_underwriting(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calls the partner underwriting API with the provided payload.
        Handles errors, logs requests/responses, and normalizes output.
        """
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        url = f"{self.base_url}/underwriting"
        try:
            logger.info(f"Submitting underwriting request to {url}")
            safe_payload = {k: v for k, v in payload.items() if k != "sensitive_field"}
            logger.debug("Request payload: %s", safe_payload)
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                logger.info(f"Received underwriting response: status={response.status_code}")
                # Normalize response to contract
                return self._normalize_response(data)
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from partner underwriting API: {e.response.status_code} {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error connecting to partner underwriting API: {e}")
            raise
        except Exception:
            logger.exception("Unexpected error in underwriting service")
            raise

    def _normalize_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize partner API response to internal contract format.
        """
        # Example normalization; adjust as needed for your partner's schema
        normalized = {
            "quote_id": data.get("quote_id") or data.get("id"),
            "premium": data.get("premium"),
            "currency": data.get("currency", "UGX"),
            "decision_status": data.get("decision_status") or data.get("status"),
            "requirements": data.get("requirements", []),
            # Add more fields as needed
        }
        # Validate/clean output
        return UnderwritingContract(**normalized).dict()
