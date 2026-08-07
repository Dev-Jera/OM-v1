
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List
from .interfaces import PaymentRequest, PaymentResponse, PaymentStatus

"""
Payment contracts.

Defines the expected request/response structures for payment operations, e.g.:
- initiating a payment
- checking payment status

These contracts must be used by both:
- clients/mocks/payments.py (fake responses for development/testing)
- clients/real_http/payments.py (real API calls when available)

Why:
- Keeps responses consistent across environments
- Helps prevent rework when the real API arrives
- Allows the chatbot to be tested end-to-end using mocks
"""
"""
Payment contract — request/response schemas and validation helpers
specific to the mobile money payment flow.
"""

# ---------------------------------------------------------------------------
# Extended payment models
# ---------------------------------------------------------------------------


@dataclass
class BulkPaymentRequest:
    """Disburse payments to multiple subscribers in one call."""
    batch_reference: str
    payments: List[PaymentRequest]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BulkPaymentResponse:
    batch_reference: str
    total: int
    successful: int
    failed: int
    results: List[PaymentResponse] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PaymentWebhookEvent:
    """Payload received from a provider webhook callback."""
    event_id: str
    provider_reference: str
    our_reference: str
    status: PaymentStatus
    amount: float
    currency: str
    phone_number: str
    timestamp: datetime
    raw_payload: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_payment_request(request: PaymentRequest) -> List[str]:
    """
    Return a list of validation errors.
    Empty list means the request is valid.
    """
    errors: List[str] = []

    if not request.reference:
        errors.append("reference is required")
    if not request.phone_number:
        errors.append("phone_number is required")
    if request.amount <= 0:
        errors.append("amount must be greater than zero")
    if not request.currency:
        errors.append("currency is required")
    if not request.description:
        errors.append("description is required")

    # Basic Ugandan phone number sanity check
    phone = request.phone_number.lstrip("+").lstrip("256")
    if len(phone) not in (9, 10):
        errors.append(f"phone_number '{request.phone_number}' does not look valid")

    return errors


def is_terminal_status(status: PaymentStatus) -> bool:
    """Return True if the payment has reached a final, non-changeable state."""
    return status in {PaymentStatus.SUCCESS, PaymentStatus.FAILED, PaymentStatus.REVERSED}
