"""Integration mode configuration helpers.

Single source of truth for deciding whether to use real (live) partner APIs
or the local mock/rule-based implementations.

Usage::

    from src.integrations.config import should_use_real_integrations

    if should_use_real_integrations():
        client = RealHttpClient(...)
    else:
        client = MockClient()

Environment variables
---------------------
INTEGRATIONS_MODE
    Set to ``real`` or ``live`` to force real APIs.
    Set to ``mock`` or ``test`` to force mocks.
    Omit (or set to anything else) to auto-detect based on partner URL variables.

PARTNER_*_API_URL
    Any of ``PARTNER_UNDERWRITING_API_URL``, ``PARTNER_QUOTATION_API_URL``,
    ``PARTNER_POLICY_API_URL``, ``PARTNER_PAYMENT_API_URL``.
    If any is set and ``INTEGRATIONS_MODE`` is not explicitly ``mock``/``test``,
    real integrations are enabled.
"""

import os


def should_use_real_integrations() -> bool:
    """Return ``True`` when the environment is configured to call real partner APIs."""
    mode = os.getenv("INTEGRATIONS_MODE", "").strip().lower()
    if mode in {"real", "live"}:
        return True
    if mode in {"mock", "test"}:
        return False
    return bool(
        os.getenv("PARTNER_UNDERWRITING_API_URL")
        or os.getenv("PARTNER_QUOTATION_API_URL")
        or os.getenv("PARTNER_POLICY_API_URL")
        or os.getenv("PARTNER_PAYMENT_API_URL")
    )
