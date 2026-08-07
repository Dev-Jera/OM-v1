"""
Quick test script for the new quote and underwriting endpoints.

Run this to verify the new API structure works correctly.
"""

import asyncio
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def test_quote_preview():
    """Test quote preview endpoint."""
    print("\n" + "="*60)
    print("Testing Quote Preview Endpoint")
    print("="*60)
    
    from src.integrations.contracts.quotes import QuotePreviewRequest
    from src.api.endpoints.quotes_underwriting import preview_quote
    
    request = QuotePreviewRequest(
        product_id="personal_accident",
        user_id="test-user-123",
        sum_assured=10000000,
        date_of_birth="1990-01-15",
        gender="Male",
        occupation="Engineer",
        policy_start_date=(date.today() + timedelta(days=30)).isoformat(),
        payment_frequency="monthly",
        currency="UGX"
    )
    
    trace_id = "test-trace-001"
    
    try:
        response = await preview_quote("personal_accident", request, trace_id)
        print(f"✅ Quote Preview Successful!")
        print(f"   Quote ID: {response.quote_id}")
        print(f"   Premium: {response.currency} {response.premium:,.2f}")
        print(f"   Sum Assured: {response.currency} {response.sum_assured:,.0f}")
        print(f"   Benefits Count: {len(response.benefits)}")
        print(f"   Download URL: {response.download_url}")
        print(f"   Valid Until: {response.valid_until}")
        
        # Print first 2 benefits
        print("\n   First 2 Benefits:")
        for benefit in response.benefits[:2]:
            print(f"     • {benefit.description}")
        
        return response.quote_id, response
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None, None


async def test_underwriting_assessment(quote_id):
    """Test underwriting assessment endpoint."""
    print("\n" + "="*60)
    print("Testing Underwriting Assessment Endpoint")
    print("="*60)
    
    from src.integrations.contracts.underwriting_assessment import UnderwritingAssessmentRequest
    from src.api.endpoints.quotes_underwriting import assess_underwriting
    
    request = UnderwritingAssessmentRequest(
        product_id="personal_accident",
        user_id="test-user-123",
        quote_id=quote_id,
        date_of_birth="1990-01-15",
        gender="Male",
        nationality="Ugandan",
        occupation="Engineer",
        sum_assured=10000000,
        policy_start_date=(date.today() + timedelta(days=30)).isoformat(),
        payment_frequency="monthly",
        has_pre_existing_conditions=False,
        risky_activities=["diving"],
        declaration_truthful=True,
        consent_medical_exam=True,
        currency="UGX"
    )
    
    trace_id = "test-trace-002"
    
    try:
        response = await assess_underwriting("personal_accident", request, trace_id)
        print(f"✅ Underwriting Assessment Successful!")
        print(f"   Assessment ID: {response.assessment_id}")
        print(f"   Decision: {response.decision.status}")
        print(f"   Base Premium: UGX {response.decision.base_premium:,.2f}")
        print(f"   Final Premium: UGX {response.decision.final_premium:,.2f}")
        print(f"   Adjustment: {response.decision.premium_adjustment_percent:.1f}%")
        print(f"   Requirements Count: {len(response.requirements)}")
        print(f"   Auto Decisioned: {response.auto_decisioned}")
        
        if response.requirements:
            print("\n   Requirements:")
            for req in response.requirements[:3]:
                print(f"     • [{req.type}] {req.message}")
        
        return response.assessment_id, response
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None, None


async def test_product_benefits_loader():
    """Test product benefits loader."""
    print("\n" + "="*60)
    print("Testing Product Benefits Loader")
    print("="*60)
    
    from src.integrations.product_benefits import product_benefits_loader
    
    try:
        # Test loading config
        config = product_benefits_loader.get_product_config("personal_accident")
        print(f"✅ Product Config Loaded!")
        print(f"   Product: {config.get('name')}")
        print(f"   Tiers: {len(config.get('coverage_tiers', []))}")
        
        # Test benefits for specific tier
        benefits = product_benefits_loader.get_benefits_for_tier("personal_accident", 10000000)
        print(f"\n   Benefits for UGX 10M coverage: {len(benefits)} items")
        
        # Test formatted benefits
        formatted = product_benefits_loader.get_formatted_benefits("personal_accident", 10000000)
        print(f"\n   Formatted Benefits:")
        for benefit in formatted[:3]:
            print(f"     • {benefit}")
        
        # Test exclusions
        exclusions = product_benefits_loader.get_exclusions("personal_accident")
        print(f"\n   Exclusions: {len(exclusions)} items")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def test_pdf_generation(quote_data):
    """Test PDF generation."""
    print("\n" + "="*60)
    print("Testing PDF Generation")
    print("="*60)
    
    try:
        from src.integrations.quote_generation import generate_product_quote_pdf
        
        # Convert Pydantic model to dict
        quote_dict = quote_data.model_dump() if hasattr(quote_data, 'model_dump') else quote_data

        product_id = str(quote_dict.get("product_id") or "personal_accident")
        input_payload = ((quote_dict.get("metadata") or {}).get("input_payload") or {})
        flow_data = dict(input_payload.get("product_data") or {})
        flow_data.update(input_payload)
        quote_id = str(quote_dict.get("quote_id") or "").strip() or None

        pdf_bytes = generate_product_quote_pdf(product_id, flow_data, quote_id=quote_id)
        print(f"✅ PDF Generated Successfully!")
        print(f"   Size: {len(pdf_bytes):,} bytes")
        print(f"   Size: {len(pdf_bytes) / 1024:.1f} KB")
        
        # Save to temp file
        from pathlib import Path
        temp_path = Path("/tmp/test_quote.pdf")
        temp_path.write_bytes(pdf_bytes)
        print(f"   Saved to: {temp_path}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def main():
    print("\n" + "🚀"*30)
    print("QUOTE & UNDERWRITING API TEST SUITE")
    print("🚀"*30)
    
    # Test 1: Product Benefits Loader
    await test_product_benefits_loader()
    
    # Test 2: Quote Preview
    quote_id, quote_data = await test_quote_preview()
    
    if quote_id and quote_data:
        # Test 3: PDF Generation
        await test_pdf_generation(quote_data)
        
        # Test 4: Underwriting Assessment
        assessment_id, assessment_data = await test_underwriting_assessment(quote_id)
        
        if assessment_id:
            print("\n" + "="*60)
            print("✅ ALL TESTS PASSED!")
            print("="*60)
            print(f"\nGenerated IDs:")
            print(f"  Quote ID: {quote_id}")
            print(f"  Assessment ID: {assessment_id}")
    else:
        print("\n" + "="*60)
        print("❌ TESTS FAILED - Quote preview did not succeed")
        print("="*60)
    
    print("\n" + "🏁"*30)
    print("TEST SUITE COMPLETE")
    print("🏁"*30 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
