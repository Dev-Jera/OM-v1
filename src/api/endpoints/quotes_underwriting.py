"""
Product-agnostic quote and underwriting endpoints.

Provides versioned REST APIs for:
- Quote preview (indicative quotes before underwriting)
- Underwriting assessment (risk evaluation)
- Quote finalization (binding quotes after assessment)
- Quote/assessment retrieval

Design principles:
- Product-agnostic: works for any insurance product via product_id
- Contract-first: strict request/response schemas
- Swappable: mock vs real via environment config
- Testable: each endpoint independently testable
- Observable: structured logging with trace_id
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Header, Depends, Request
from fastapi.responses import Response

from src.integrations.contracts.quotes import (
    QuotePreviewRequest,
    QuotePreviewResponse,
    FinalQuoteRequest,
    FinalQuoteResponse,
    QuoteRetrievalResponse,
    BenefitItem,
    PremiumBreakdown,
)
from src.integrations.contracts.underwriting_assessment import (
    UnderwritingAssessmentRequest,
    UnderwritingAssessmentResponse,
    UnderwritingDecision,
    RequirementItem,
    UnderwritingRetrievalResponse,
)
from src.integrations.product_benefits import product_benefits_loader
from src.integrations.quote_generation import generate_and_register_quote_pdf
from src.integrations.quote_downloads import (
    get_quote_metadata,
    get_quote_pdf,
    register_quote_pdf,
    build_download_url,
)
from src.chatbot.dependencies import session_user_id_from_request


def _require_quote_owner(request: Request, quote: Dict[str, Any]) -> None:
    owner = quote.get("user_id") or (quote.get("metadata") or {}).get("user_id")
    if not owner or owner != session_user_id_from_request(request):
        raise HTTPException(status_code=403, detail="Quote access denied")
from src.integrations.notifications import email_service
from src.integrations.underwriting import run_quote_preview
from src.integrations.policy.journey_orchestrator import journey_orchestrator

logger = logging.getLogger(__name__)

api = APIRouter(prefix="/v1/products", tags=["Product Quotes & Underwriting"])


_assessments_store: Dict[str, Dict[str, Any]] = {}


def _get_trace_id(x_trace_id: Optional[str] = Header(None)) -> str:
    """Get or generate trace ID for request tracking."""
    return x_trace_id or f"trace-{uuid4().hex[:16]}"


@api.post("/{product_id}/quotes/preview")
async def preview_quote(
    product_id: str,
    request: QuotePreviewRequest,
    trace_id: str = Depends(_get_trace_id),
) -> QuotePreviewResponse:
    """
    Generate an indicative (non-binding) quote preview.

    This endpoint provides a quick premium estimate based on basic information.
    The quote is NOT binding and may change after full underwriting assessment.

    Use cases:
    - Show customers an instant quote before collecting detailed information
    - Display benefits and exclusions for a coverage tier
    - Allow quote download before commitment

    **Important:** This is an estimate. Final premium determined after underwriting.
    """
    logger.info(f"[{trace_id}] Quote preview requested for {product_id}", extra={
        "trace_id": trace_id,
        "product_id": product_id,
        "user_id": request.user_id,
    })

    try:
        # Normalize sum assured
        sum_assured = request.sum_assured or request.cover_limit_ugx
        if not sum_assured:
            raise HTTPException(status_code=400, detail="sum_assured or cover_limit_ugx is required")

        # Load product benefits and configuration
        benefits_data = product_benefits_loader.get_benefits_for_tier(product_id, sum_assured)
        exclusions = product_benefits_loader.get_exclusions(product_id)
        assumptions = product_benefits_loader.get_important_notes(product_id)

        # Convert benefits to contract format
        benefits = [
            BenefitItem(
                code=b.get("code", ""),
                description=product_benefits_loader.format_benefit_description(b),
                amount=b.get("amount"),
                unit=b.get("unit"),
            )
            for b in benefits_data
        ]

        # Run quote preview (calls underwriting mock or service)
        preview_result = await run_quote_preview(
            user_id=request.user_id,
            product_id=product_id,
            underwriting_data={
                "dob": request.date_of_birth,
                "gender": request.gender,
                "occupation": request.occupation,
                "coverLimitAmountUgx": str(int(sum_assured)),
                "policyStartDate": request.policy_start_date,
                **request.product_data,
            },
            currency=request.currency,
            metadata=request.metadata,
        )

        # Extract underwriting and quotation data
        underwriting = preview_result.get("underwriting", {})
        quotation = preview_result.get("quotation", {})

        quote_id = quotation.get("quote_id") or underwriting.get("quote_id") or f"QT-{uuid4().hex[:12].upper()}"
        premium = quotation.get("amount") or quotation.get("premium") or underwriting.get("premium", 0)

        # Build premium breakdown
        breakdown_data = quotation.get("breakdown") or underwriting.get("breakdown", {})
        breakdown = PremiumBreakdown(
            base_premium=breakdown_data.get("annual_base", breakdown_data.get("base_monthly", breakdown_data.get("base_premium", 0))),
            age_loading=breakdown_data.get("age_modifier_amount", breakdown_data.get("age_loading", 0)),
            risk_loading=breakdown_data.get("risk_loading", breakdown_data.get("region_fee", 0)),
            levies=breakdown_data.get("levies", breakdown_data.get("training_levy", 0) + breakdown_data.get("sticker_fee", 0)),
            taxes=breakdown_data.get("taxes", breakdown_data.get("vat", 0)),
            total=premium,
            frequency=request.payment_frequency,
            annual_equivalent=breakdown_data.get("annual_total"),
            metadata=breakdown_data,
        )

        # Generate PDF
        pdf_url = None
        product_name = product_benefits_loader.get_product_config(product_id).get("name", product_id)
        flow_data = dict(request.product_data or {})
        flow_data.update(
            {
                "date_of_birth": request.date_of_birth,
                "dob": request.date_of_birth,
                "gender": request.gender,
                "occupation": request.occupation,
                "cover_limit_ugx": sum_assured,
                "sum_assured": sum_assured,
                "coverLimitAmountUgx": str(int(sum_assured)),
                "policy_start_date": request.policy_start_date,
                "policyStartDate": request.policy_start_date,
            }
        )
        try:
            quote_result = generate_and_register_quote_pdf(
                product_id,
                flow_data,
                quote_id=quote_id,
                product_name=product_name,
            )
            pdf_url = quote_result.get("download_url") or None
        except Exception as e:
            logger.warning(f"Failed to generate PDF: {e}")

        # Create response
        response = QuotePreviewResponse(
            quote_id=quote_id,
            product_id=product_id,
            product_name=product_name,
            status="preview",
            is_binding=False,
            premium=premium,
            currency=request.currency,
            payment_frequency=request.payment_frequency,
            breakdown=breakdown,
            sum_assured=sum_assured,
            benefits=benefits,
            policy_start_date=request.policy_start_date,
            policy_duration_months=12,
            assumptions=assumptions,
            exclusions=exclusions,
            important_notes=[],
            download_url=pdf_url,
            valid_until=(datetime.utcnow() + timedelta(days=30)).isoformat(),
            metadata={
                "trace_id": trace_id,
                "input_payload": request.dict(),
                "normalized_sum_assured": sum_assured,
            },
        )

        # Store quote
        register_quote_pdf(quote_id, metadata=response.dict())

        logger.info(f"[{trace_id}] Quote preview generated: {quote_id}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{trace_id}] Failed to generate quote preview")
        raise HTTPException(status_code=500, detail="Failed to generate quote")


@api.post("/{product_id}/underwriting/assess")
async def assess_underwriting(
    product_id: str,
    request: UnderwritingAssessmentRequest,
    trace_id: str = Depends(_get_trace_id),
) -> UnderwritingAssessmentResponse:
    """
    Perform full underwriting assessment with risk evaluation.

    This endpoint performs comprehensive risk assessment including:
    - Medical/health screening
    - Insurance history check
    - Risk factor analysis
    - Premium adjustment calculation
    - Decision (APPROVED/DECLINED/REFERRED)

    Use after collecting complete customer information and disclosures.

    Returns decision and any requirements/exclusions.
    """
    logger.info(f"[{trace_id}] Underwriting assessment for {product_id}", extra={
        "trace_id": trace_id,
        "product_id": product_id,
        "user_id": request.user_id,
    })

    try:
        # Build underwriting payload
        underwriting_payload = {
            "user_id": request.user_id,
            "product_id": product_id,
            "coverLimitAmountUgx": str(int(request.sum_assured)),
            "dob": request.date_of_birth,
            "gender": request.gender,
            "occupation": request.occupation,
            "riskyActivities": request.risky_activities,
            "policyStartDate": request.policy_start_date,
            "has_pre_existing_conditions": request.has_pre_existing_conditions,
            "pre_existing_conditions": request.pre_existing_conditions,
            "smoker": request.smoker,
            **request.product_specific_data,
        }

        # Run local underwriting logic through unified orchestrator
        preview_result = await journey_orchestrator.run_underwriting_and_quotation_preview(
            user_id=request.user_id,
            product_id=product_id,
            underwriting_data=underwriting_payload,
            currency="UGX",
            metadata={},
        )
        underwriting_raw = preview_result.get("underwriting") or {}

        # Parse results
        assessment_id = f"UW-{uuid4().hex[:12].upper()}"
        decision_status = underwriting_raw.get("decision_status", "APPROVED")
        base_premium = underwriting_raw.get("breakdown", {}).get("annual_base", 0)
        final_premium = underwriting_raw.get("premium", 0)
        requirements = [
            RequirementItem(
                type=req.get("type", "info"),
                field=req.get("field"),
                message=req.get("message", ""),
                severity="blocker" if req.get("type") == "eligibility" else "warning",
            )
            for req in underwriting_raw.get("requirements", [])
        ]

        # Build decision
        decision = UnderwritingDecision(
            status=decision_status,
            base_premium=base_premium,
            final_premium=final_premium,
            premium_adjustment_percent=((final_premium - base_premium) / base_premium * 100) if base_premium > 0 else 0,
            adjustment_reasons=[],
            decline_reasons=[req.message for req in requirements if req.type == "eligibility"],
            referral_reasons=[req.message for req in requirements if req.type == "underwriting"],
        )

        # Create response
        response = UnderwritingAssessmentResponse(
            assessment_id=assessment_id,
            product_id=product_id,
            user_id=request.user_id,
            quote_id=request.quote_id,
            decision=decision,
            requirements=requirements,
            risk_score=None,
            risk_category=None,
            risk_factors=[],
            valid_until=(datetime.utcnow() + timedelta(days=30)).isoformat(),
            auto_decisioned=True,
            requires_manual_review=(decision_status == "REFERRED"),
            metadata={"trace_id": trace_id, "underwriting_raw": underwriting_raw},
        )

        # Store assessment
        _assessments_store[assessment_id] = response.dict()

        logger.info(f"[{trace_id}] Assessment complete: {assessment_id} - {decision_status}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{trace_id}] Failed to assess underwriting")
        raise HTTPException(status_code=500, detail="Assessment failed")


@api.post("/{product_id}/quotes/finalize")
async def finalize_quote(
    product_id: str,
    request: FinalQuoteRequest,
    trace_id: str = Depends(_get_trace_id),
) -> FinalQuoteResponse:
    """
    Finalize a quote after successful underwriting assessment.

    Converts an indicative quote to a binding quote ready for payment.
    Requires an approved underwriting assessment.

    This quote is binding and can be used for policy issuance after payment.
    """
    logger.info(f"[{trace_id}] Finalizing quote {request.quote_id}", extra={
        "trace_id": trace_id,
        "product_id": product_id,
        "quote_id": request.quote_id,
    })

    try:
        # Retrieve original quote and assessment
        original_quote = get_quote_metadata(request.quote_id)
        if not original_quote:
            raise HTTPException(status_code=404, detail=f"Quote {request.quote_id} not found")

        assessment = _assessments_store.get(request.underwriting_assessment_id)
        if not assessment:
            raise HTTPException(status_code=404, detail=f"Assessment {request.underwriting_assessment_id} not found")

        if assessment["decision"]["status"] != "APPROVED":
            raise HTTPException(status_code=400, detail="Cannot finalize quote with non-approved assessment")

        # Use updated premium or original
        final_premium = request.updated_premium or assessment["decision"]["final_premium"]

        # Build final quote
        final_quote_id = f"FQ-{uuid4().hex[:12].upper()}"
        final_quote_pdf = get_quote_pdf(request.quote_id)
        final_download_url = build_download_url(final_quote_id) if final_quote_pdf else None

        response = FinalQuoteResponse(
            quote_id=final_quote_id,
            product_id=product_id,
            product_name=original_quote["product_name"],
            status="final",
            is_binding=True,
            premium=final_premium,
            currency=original_quote["currency"],
            payment_frequency=original_quote["payment_frequency"],
            breakdown=PremiumBreakdown(**original_quote["breakdown"]),
            sum_assured=original_quote["sum_assured"],
            benefits=[BenefitItem(**b) for b in original_quote["benefits"]],
            policy_start_date=original_quote["policy_start_date"],
            policy_end_date=(datetime.fromisoformat(original_quote["policy_start_date"]) + timedelta(days=365)).isoformat()[:10],
            policy_duration_months=12,
            exclusions=original_quote["exclusions"] + request.additional_exclusions,
            special_terms=request.special_terms,
            download_url=final_download_url,
            underwriting_assessment_id=request.underwriting_assessment_id,
            valid_until=(datetime.utcnow() + timedelta(days=30)).isoformat(),
            payment_required=True,
            payment_amount=final_premium,
            metadata={
                "trace_id": trace_id,
                "original_quote_id": request.quote_id,
                "original_input_payload": (original_quote.get("metadata", {}) or {}).get("input_payload", {}),
                "finalization_input_payload": request.dict(),
            },
        )

        # Store final quote (and carry forward PDF bytes when available).
        register_quote_pdf(final_quote_id, pdf_bytes=final_quote_pdf, metadata=response.dict())

        # Send final quote email without failing quote finalization on send issues.
        original_input = (response.metadata or {}).get("original_input_payload", {}) or {}
        recipient = str(
            original_input.get("email")
            or original_input.get("email_address")
            or request.metadata.get("email")
            or request.metadata.get("customer_email")
            or ""
        ).strip()
        email_result: Dict[str, Any]
        if recipient:
            email_result = email_service.send_final_quote_email(
                to_email=recipient,
                quote_payload=response.dict(),
                attachment_bytes=final_quote_pdf,
                attachment_filename=f"quote_{final_quote_id}.pdf",
            )
        else:
            email_result = {
                "sent": False,
                "provider": "smtp",
                "reason": "missing_recipient",
            }

        response.metadata["final_quote_email"] = email_result
        register_quote_pdf(final_quote_id, metadata=response.dict())

        logger.info(f"[{trace_id}] Final quote created: {final_quote_id}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{trace_id}] Failed to finalize quote")
        raise HTTPException(status_code=500, detail="Finalization failed")


@api.get("/quotes/{quote_id}")
async def get_quote(quote_id: str, request: Request) -> QuoteRetrievalResponse:
    """Retrieve an existing quote by ID."""
    quote = get_quote_metadata(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail=f"Quote {quote_id} not found")
    _require_quote_owner(request, quote)

    return QuoteRetrievalResponse(
        quote_id=quote["quote_id"],
        product_id=quote["product_id"],
        product_name=quote["product_name"],
        status=quote["status"],
        is_binding=quote["is_binding"],
        premium=quote["premium"],
        currency=quote["currency"],
        sum_assured=quote["sum_assured"],
        created_at=quote["created_at"],
        valid_until=quote.get("valid_until"),
        download_url=quote.get("download_url"),
        metadata=quote.get("metadata", {}),
    )


@api.get("/quotes/{quote_id}/download")
async def download_quote_pdf(quote_id: str, request: Request):
    """Download quote as PDF."""
    pdf_bytes = get_quote_pdf(quote_id)
    if not pdf_bytes:
        raise HTTPException(status_code=404, detail=f"PDF not found for quote {quote_id}")
    quote = get_quote_metadata(quote_id) or {}
    _require_quote_owner(request, quote)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=quote_{quote_id}.pdf"
        }
    )


@api.get("/underwriting/{assessment_id}")
async def get_assessment(assessment_id: str) -> UnderwritingRetrievalResponse:
    """Retrieve an existing underwriting assessment by ID."""
    assessment = _assessments_store.get(assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail=f"Assessment {assessment_id} not found")

    return UnderwritingRetrievalResponse(
        assessment_id=assessment["assessment_id"],
        product_id=assessment["product_id"],
        user_id=assessment["user_id"],
        quote_id=assessment.get("quote_id"),
        decision_status=assessment["decision"]["status"],
        final_premium=assessment["decision"]["final_premium"],
        created_at=assessment["created_at"],
        auto_decisioned=assessment["auto_decisioned"],
        metadata=assessment.get("metadata", {}),
    )


__all__ = ["api"]
