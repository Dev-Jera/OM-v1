from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class KYCStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"
    CLAIMED = "CLAIMED"


class Provider(str, Enum):
    MTN = "MTN"
    AIRTEL = "AIRTEL"


# ---------------------------------------------------------------------------
# Shared data models
# ---------------------------------------------------------------------------

@dataclass
class Address:
    district: str
    region: str
    country: str = "Uganda"
    village: Optional[str] = None


@dataclass
class Beneficiary:
    full_name: str
    phone_number: str
    relationship: str
    percentage: float                    # share of payout, must sum to 100


@dataclass
class CustomerProfile:
    customer_id: str
    full_name: str
    phone_number: str
    national_id: str
    date_of_birth: str                   # ISO format: YYYY-MM-DD
    gender: str                          # M / F
    address: Address
    kyc_status: KYCStatus
    beneficiaries: List[Beneficiary] = field(default_factory=list)
    email: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PaymentRequest:
    reference: str
    phone_number: str
    amount: float
    currency: str
    description: str
    customer_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PaymentResponse:
    reference: str
    provider_reference: str
    status: PaymentStatus
    amount: float
    currency: str
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Product:
    product_id: str
    name: str
    description: str
    premium_amount: float
    currency: str
    cover_amount: float
    duration_months: int
    eligible_age_min: int
    eligible_age_max: int
    features: List[str] = field(default_factory=list)
    exclusions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyApplication:
    application_id: str
    customer_id: str
    product_id: str
    beneficiaries: List[Beneficiary]
    payment_reference: str
    status: PolicyStatus
    start_date: str                      # ISO format: YYYY-MM-DD
    end_date: str
    premium_amount: float
    cover_amount: float
    currency: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract provider interface
# ---------------------------------------------------------------------------

class MobileMoneyProvider(ABC):
    """Every mobile money provider client must implement this interface."""

    @property
    @abstractmethod
    def provider(self) -> Provider:
        """Return the provider enum value."""

    # -- Payments --

    @abstractmethod
    def initiate_payment(self, request: PaymentRequest) -> PaymentResponse:
        """Initiate a mobile money collection (debit from subscriber)."""

    @abstractmethod
    def check_payment_status(self, reference: str) -> PaymentResponse:
        """Poll the status of a previously initiated payment."""

    @abstractmethod
    def reverse_payment(self, reference: str, reason: str) -> PaymentResponse:
        """Reverse / refund a successful payment."""

    # -- Customer onboarding --

    @abstractmethod
    def create_customer(self, profile: CustomerProfile) -> CustomerProfile:
        """Register a new policy buyer."""

    @abstractmethod
    def get_customer(self, customer_id: str) -> Optional[CustomerProfile]:
        """Fetch an existing customer by ID."""

    @abstractmethod
    def update_customer(self, customer_id: str, updates: Dict[str, Any]) -> CustomerProfile:
        """Update customer details."""

    @abstractmethod
    def verify_kyc(self, customer_id: str) -> KYCStatus:
        """Trigger or check KYC verification for a customer."""

    @abstractmethod
    def add_beneficiary(self, customer_id: str, beneficiary: Beneficiary) -> CustomerProfile:
        """Add a beneficiary to a customer's profile."""

    # -- Products --

    @abstractmethod
    def list_products(self) -> List[Product]:
        """Return all available insurance products."""

    @abstractmethod
    def get_product(self, product_id: str) -> Optional[Product]:
        """Fetch a single product by ID."""

    # -- Policy --

    @abstractmethod
    def apply_for_policy(self, application: PolicyApplication) -> PolicyApplication:
        """Submit a policy application."""

    @abstractmethod
    def get_policy(self, application_id: str) -> Optional[PolicyApplication]:
        """Retrieve a policy application by ID."""

    @abstractmethod
    def cancel_policy(self, application_id: str, reason: str) -> PolicyApplication:
        """Cancel an active policy."""
