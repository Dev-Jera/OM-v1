"""
Quote contracts for standardized quote preview, finalization, and retrieval.

These contracts define the structure for:
- Quote preview requests/responses (indicative quotes before underwriting)
- Final quote requests/responses (bindable quotes after underwriting approval)
- Quote retrieval and status queries

Used by:
- Quote preview endpoints (early estimation)
- Quote finalization endpoints (post-underwriting binding)
- Product-specific quote builders (personal_accident, serenicare, motor, etc.)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class QuotePreviewRequest(BaseModel):
    """Request for an indicative (non-binding) quote preview."""

    product_id: str = Field(..., description="Product identifier (e.g., 'personal_accident', 'serenicare')")
    user_id: str = Field(..., description="User requesting the quote")

    # Basic inputs for quick quote calculation
    sum_assured: Optional[float] = Field(None, description="Coverage amount requested")
    cover_limit_ugx: Optional[float] = Field(None, description="Alternative field for coverage amount")

    # Customer basic info
    date_of_birth: Optional[str] = Field(None, description="Customer DOB (ISO format YYYY-MM-DD)")
    gender: Optional[str] = Field(None, description="Customer gender (Male/Female/Other)")
    occupation: Optional[str] = Field(None, description="Customer occupation")

    # Policy details
    policy_start_date: Optional[str] = Field(None, description="Policy start date (ISO format)")
    payment_frequency: Optional[str] = Field("monthly", description="Payment frequency (monthly/quarterly/annually)")

    # Product-specific data (flexible for different products)
    product_data: Dict[str, Any] = Field(default_factory=dict, description="Product-specific fields")

    # Metadata
    currency: str = Field("UGX", description="Currency code")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class BenefitItem(BaseModel):
    """A single benefit offered by the product at this coverage level."""

    code: str = Field(..., description="Benefit code/identifier")
    description: str = Field(..., description="Human-readable benefit description")
    amount: Optional[float] = Field(None, description="Benefit amount (if applicable)")
    unit: Optional[str] = Field(None, description="Unit (e.g., 'per day', 'max days')")


class PremiumBreakdown(BaseModel):
    """Detailed breakdown of premium calculation."""

    base_premium: float = Field(..., description="Base premium before loadings/discounts")
    age_loading: float = Field(0.0, description="Age-based loading/discount")
    gender_loading: float = Field(0.0, description="Gender-based loading/discount")
    occupation_loading: float = Field(0.0, description="Occupation risk loading")
    risk_loading: float = Field(0.0, description="Additional risk loading (e.g., risky activities)")
    discounts: float = Field(0.0, description="Any applicable discounts")
    levies: float = Field(0.0, description="Regulatory levies")
    taxes: float = Field(0.0, description="VAT or other taxes")
    total: float = Field(..., description="Total premium amount")

    # Additional context
    frequency: str = Field("monthly", description="Premium frequency")
    annual_equivalent: Optional[float] = Field(None, description="Annual premium amount")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional breakdown details")


class QuotePreviewResponse(BaseModel):
    """Response containing an indicative quote preview."""

    quote_id: str = Field(..., description="Unique quote identifier")
    product_id: str = Field(..., description="Product identifier")
    product_name: str = Field(..., description="Product display name")

    # Quote status
    status: str = Field("preview", description="Quote status (preview/indicative)")
    is_binding: bool = Field(False, description="Whether this quote is binding (preview quotes are not)")

    # Premium information
    premium: float = Field(..., description="Premium amount")
    currency: str = Field(..., description="Currency code")
    payment_frequency: str = Field(..., description="Payment frequency")
    breakdown: PremiumBreakdown = Field(..., description="Premium calculation breakdown")

    # Coverage information
    sum_assured: float = Field(..., description="Coverage amount")
    benefits: List[BenefitItem] = Field(default_factory=list, description="List of benefits included")

    # Policy details
    policy_start_date: Optional[str] = Field(None, description="Proposed policy start date")
    policy_duration_months: int = Field(12, description="Policy duration in months")

    # Important notices
    assumptions: List[str] = Field(default_factory=list, description="Assumptions made for this quote")
    exclusions: List[str] = Field(default_factory=list, description="Standard exclusions")
    important_notes: List[str] = Field(default_factory=list, description="Important information")

    # Download capability
    download_url: Optional[str] = Field(None, description="URL to download quote PDF")

    # Validity
    valid_until: Optional[str] = Field(None, description="Quote validity expiration (ISO datetime)")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat(), description="Quote creation timestamp")

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional quote data")


class FinalQuoteRequest(BaseModel):
    """Request to finalize a quote after underwriting approval."""

    quote_id: str = Field(..., description="Quote ID from preview")
    user_id: str = Field(..., description="User requesting finalization")
    underwriting_assessment_id: str = Field(..., description="Approved underwriting assessment ID")

    # Updated details (if any changed during underwriting)
    updated_premium: Optional[float] = Field(None, description="Updated premium if repriced during underwriting")
    additional_exclusions: List[str] = Field(default_factory=list, description="Additional exclusions added during underwriting")
    special_terms: List[str] = Field(default_factory=list, description="Special terms/conditions from underwriting")

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FinalQuoteResponse(BaseModel):
    """Response containing a finalized, bindable quote."""

    quote_id: str = Field(..., description="Final quote identifier")
    product_id: str = Field(..., description="Product identifier")
    product_name: str = Field(..., description="Product display name")

    # Quote status
    status: str = Field("final", description="Quote status")
    is_binding: bool = Field(True, description="This quote is binding and ready for payment")

    # Premium information
    premium: float = Field(..., description="Final premium amount")
    currency: str = Field(..., description="Currency code")
    payment_frequency: str = Field(..., description="Payment frequency")
    breakdown: PremiumBreakdown = Field(..., description="Premium calculation breakdown")

    # Coverage information
    sum_assured: float = Field(..., description="Coverage amount")
    benefits: List[BenefitItem] = Field(default_factory=list, description="List of benefits included")

    # Policy details
    policy_start_date: str = Field(..., description="Policy start date")
    policy_end_date: str = Field(..., description="Policy end date")
    policy_duration_months: int = Field(..., description="Policy duration in months")

    # Terms & conditions
    exclusions: List[str] = Field(default_factory=list, description="All applicable exclusions")
    special_terms: List[str] = Field(default_factory=list, description="Special terms from underwriting")

    # Download
    download_url: Optional[str] = Field(None, description="URL to download final quote PDF")

    # Underwriting reference
    underwriting_assessment_id: str = Field(..., description="Associated underwriting assessment")

    # Validity
    valid_until: str = Field(..., description="Quote validity expiration (ISO datetime)")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    # Next steps
    payment_required: bool = Field(True, description="Whether payment is required to bind")
    payment_amount: float = Field(..., description="Amount required for payment")

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)


class QuoteRetrievalResponse(BaseModel):
    """Response when retrieving an existing quote."""

    quote_id: str
    product_id: str
    product_name: str
    status: str
    is_binding: bool
    premium: float
    currency: str
    sum_assured: float
    created_at: str
    valid_until: Optional[str] = None
    download_url: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "QuotePreviewRequest",
    "QuotePreviewResponse",
    "FinalQuoteRequest",
    "FinalQuoteResponse",
    "QuoteRetrievalResponse",
    "BenefitItem",
    "PremiumBreakdown",
]
