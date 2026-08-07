"""
Integrations layer.
This package contains all code used to communicate with external systems such as:
- Old Mutual underwriting APIs (quote/premium decisions)
- Payment systems (e.g., Mobile Money / payment gateways)
- Product catalogue sources (Zoho or local product files)

Key rule:
- Chatbot flows MUST NOT call external APIs directly.
- Flows should call integration clients (under src/integrations/clients).
- We use MOCK clients during development and swap to REAL_HTTP clients when APIs are available.

Switching implementations:
- The selection of mock vs real clients should happen in ONE place (src/api/main.py).
"""

from .contracts.interfaces import (
    Address,
    Beneficiary,
    CustomerProfile,
    KYCStatus,
    MobileMoneyProvider,
    PaymentRequest,
    PaymentResponse,
    PaymentStatus,
    PolicyApplication,
    PolicyStatus,
    Product,
    Provider,
)
from .contracts.underwriting import UnderwritingContract
from .contracts.payments import (
    BulkPaymentRequest,
    BulkPaymentResponse,
    PaymentWebhookEvent,
    is_terminal_status,
    validate_payment_request,
)
from .contracts.product_catalogues import (
    ProductFilter,
    ProductQuote,
    filter_products,
)

__all__ = [
    # interfaces
    "Address", "Beneficiary", "CustomerProfile", "KYCStatus",
    "MobileMoneyProvider", "PaymentRequest", "PaymentResponse",
    "PaymentStatus", "PolicyApplication", "PolicyStatus",
    "Product", "Provider",
    # underwriting
    "UnderwritingContract",
    # payments
    "BulkPaymentRequest", "BulkPaymentResponse", "PaymentWebhookEvent",
    "is_terminal_status", "validate_payment_request",
    # products
    "ProductFilter", "ProductQuote", "filter_products",
]
