"""Compatibility helpers for underwriting/quotation preview orchestration."""

from typing import Any, Dict, Optional

from src.integrations.policy.journey_orchestrator import journey_orchestrator


async def run_quote_preview(
    *,
    user_id: str,
    product_id: str,
    underwriting_data: Dict[str, Any],
    currency: str = "UGX",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generate a preview quotation for display in the chatbot flow.

    This is a lightweight version of the full underwriting-quote-policy flow.
    It provides a preview of what the quotation would look like without
    persisting it or initiating payment.

    Args:
        user_id: Unique identifier for the user
        product_id: Product identifier (e.g., "personal_accident", "serenicare")
        underwriting_data: KYC and risk assessment data
        currency: Currency code (default: "UGX")
        metadata: Additional metadata to include in requests

    Returns:
        Dictionary containing:
        - underwriting: Normalized underwriting response
        - quotation: Normalized quotation response (if successful)
        - declined: Boolean indicating if underwriting was declined
        - decision_status: Status from underwriting decision
    """
    result = await journey_orchestrator.run_underwriting_and_quotation_preview(
        user_id=user_id,
        product_id=product_id,
        underwriting_data=underwriting_data,
        currency=currency,
        metadata=metadata,
    )

    # Preserve backward-compatible shape expected by existing flows.
    result.pop("payment", None)
    return result


__all__ = ["run_quote_preview"]
