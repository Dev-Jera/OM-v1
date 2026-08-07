"""
Underwriting assessment contracts for risk evaluation and decision-making.

These contracts define the structure for:
- Underwriting assessment requests (full risk evaluation with all disclosures)
- Underwriting assessment responses (decision, requirements, loadings)
- Assessment retrieval and status queries

Used by:
- Underwriting assessment endpoints
- Product-specific underwriting builders
- Quote finalization flow
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class UnderwritingAssessmentRequest(BaseModel):
    """Request for full underwriting assessment."""

    product_id: str = Field(..., description="Product identifier")
    user_id: str = Field(..., description="User being underwritten")
    quote_id: Optional[str] = Field(None, description="Associated quote ID (if from preview flow)")

    # Personal information
    date_of_birth: str = Field(..., description="DOB (ISO format YYYY-MM-DD)")
    gender: str = Field(..., description="Gender (Male/Female/Other)")
    nationality: str = Field(..., description="Nationality")
    occupation: str = Field(..., description="Occupation")
    annual_income: Optional[float] = Field(None, description="Annual income")

    # Coverage requested
    sum_assured: float = Field(..., description="Coverage amount requested")
    policy_start_date: str = Field(..., description="Requested policy start date")
    payment_frequency: str = Field("monthly", description="Payment frequency")

    # Medical/health disclosures
    has_pre_existing_conditions: bool = Field(False, description="Any pre-existing medical conditions")
    pre_existing_conditions: List[str] = Field(default_factory=list, description="List of conditions")
    current_medications: List[str] = Field(default_factory=list, description="Current medications")
    recent_hospitalizations: List[Dict[str, Any]] = Field(default_factory=list, description="Hospitalizations in last 5 years")
    height_cm: Optional[float] = Field(None, description="Height in cm")
    weight_kg: Optional[float] = Field(None, description="Weight in kg")
    smoker: bool = Field(False, description="Tobacco use")
    alcohol_consumption: Optional[str] = Field(None, description="Alcohol consumption level")

    # Insurance history
    has_previous_policies: bool = Field(False, description="Previous insurance policies")
    previous_policies: List[Dict[str, Any]] = Field(default_factory=list, description="Previous policy details")
    claims_history: List[Dict[str, Any]] = Field(default_factory=list, description="Previous claims")
    declined_policies: List[Dict[str, Any]] = Field(default_factory=list, description="Previously declined applications")

    # Risk factors (product-specific)
    risky_activities: List[str] = Field(default_factory=list, description="Hazardous activities/hobbies")
    physical_disabilities: List[str] = Field(default_factory=list, description="Any physical disabilities")
    travel_patterns: List[Dict[str, Any]] = Field(default_factory=list, description="Frequent travel to high-risk areas")

    # Documents submitted
    documents: List[Dict[str, Any]] = Field(default_factory=list, description="Submitted documents for verification")

    # Product-specific underwriting data
    product_specific_data: Dict[str, Any] = Field(default_factory=dict, description="Product-specific fields")

    # Declarations
    declaration_truthful: bool = Field(..., description="Customer declares all information is truthful")
    consent_medical_exam: bool = Field(False, description="Consent for medical examination if required")
    consent_medical_records: bool = Field(False, description="Consent to access medical records")

    # Metadata
    currency: str = Field("UGX", description="Currency code")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RequirementItem(BaseModel):
    """A requirement or note from underwriting."""

    type: str = Field(..., description="Type: validation, eligibility, underwriting, document")
    field: Optional[str] = Field(None, description="Related field name")
    code: Optional[str] = Field(None, description="Requirement code")
    message: str = Field(..., description="Human-readable message")
    severity: str = Field("info", description="Severity: info, warning, blocker")
    action_required: Optional[str] = Field(None, description="Action customer must take")


class UnderwritingDecision(BaseModel):
    """Underwriting decision details."""

    status: str = Field(..., description="Decision: APPROVED, DECLINED, REFERRED, PENDING")
    decision_date: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    underwriter_id: Optional[str] = Field(None, description="Human underwriter ID if manually reviewed")

    # Premium adjustments
    base_premium: float = Field(..., description="Original base premium")
    final_premium: float = Field(..., description="Final premium after loadings/discounts")
    premium_adjustment_percent: float = Field(0.0, description="Total premium adjustment as percentage")
    adjustment_reasons: List[str] = Field(default_factory=list, description="Reasons for adjustments")

    # Coverage modifications
    coverage_modifications: List[str] = Field(default_factory=list, description="Any coverage changes")
    exclusions_added: List[str] = Field(default_factory=list, description="Additional exclusions")
    special_terms: List[str] = Field(default_factory=list, description="Special terms/conditions")

    # Decline/referral reasons
    decline_reasons: List[str] = Field(default_factory=list, description="Reasons for decline")
    referral_reasons: List[str] = Field(default_factory=list, description="Reasons for manual review")

    # Next steps
    next_steps: List[str] = Field(default_factory=list, description="Required next steps")

    metadata: Dict[str, Any] = Field(default_factory=dict)


class UnderwritingAssessmentResponse(BaseModel):
    """Response containing full underwriting assessment results."""

    assessment_id: str = Field(..., description="Unique assessment identifier")
    product_id: str = Field(..., description="Product identifier")
    user_id: str = Field(..., description="User ID")
    quote_id: Optional[str] = Field(None, description="Associated quote ID")

    # Decision
    decision: UnderwritingDecision = Field(..., description="Underwriting decision")

    # Requirements
    requirements: List[RequirementItem] = Field(default_factory=list, description="All requirements/notes")

    # Risk assessment details
    risk_score: Optional[float] = Field(None, description="Calculated risk score (0-100)")
    risk_category: Optional[str] = Field(None, description="Risk category: low, medium, high, very_high")
    risk_factors: List[str] = Field(default_factory=list, description="Identified risk factors")

    # Validity
    valid_until: Optional[str] = Field(None, description="Assessment validity expiration")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    # Processing info
    auto_decisioned: bool = Field(True, description="Whether decision was automated")
    requires_manual_review: bool = Field(False, description="Whether manual review is needed")
    estimated_review_time_hours: Optional[int] = Field(None, description="Est. review time if referred")

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UnderwritingRetrievalResponse(BaseModel):
    """Response when retrieving an existing assessment."""

    assessment_id: str
    product_id: str
    user_id: str
    quote_id: Optional[str] = None
    decision_status: str
    final_premium: float
    created_at: str
    auto_decisioned: bool
    metadata: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "UnderwritingAssessmentRequest",
    "UnderwritingAssessmentResponse",
    "UnderwritingDecision",
    "RequirementItem",
    "UnderwritingRetrievalResponse",
]
