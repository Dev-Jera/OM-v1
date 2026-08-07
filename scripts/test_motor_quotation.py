#!/usr/bin/env python3
"""
Test motor_private quotation and underwriting integration
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
from src.integrations.underwriting import run_quote_preview


async def test_motor_private_quotation():
    """Test that motor_private can generate quotation previews"""
    print("\n" + "="*70)
    print("Testing Motor Private Quotation/Underwriting Integration")
    print("="*70)
    
    # Simulate motor private quote request
    try:
        result = await run_quote_preview(
            user_id="test-user-123",
            product_id="motor_private",
            underwriting_data={
                "vehicleValue": "10000000",  # 10M UGX
                "vehicleMake": "Toyota",
                "yearOfManufacture": "2020",
                "coverType": "comprehensive",
                "rareModel": "no",
                "policyStartDate": "2026-04-01",
            },
            currency="UGX",
        )
        
        print("\n✅ Quotation preview generated successfully!\n")
        
        # Display key information
        quotation = result.get("quotation", {})
        underwriting = result.get("underwriting", {})
        
        print("Quotation Details:")
        print(f"  Quote ID: {quotation.get('quote_id', 'N/A')}")
        print(f"  Premium: UGX {quotation.get('premium', quotation.get('amount', 0)):,.2f}")
        print(f"  Currency: {quotation.get('currency', 'N/A')}")
        print(f"  Valid Until: {quotation.get('expires_at', 'N/A')}")
        
        print("\nUnderwriting Details:")
        print(f"  Decision: {underwriting.get('decision', 'N/A')}")
        print(f"  Quote ID: {underwriting.get('quote_id', 'N/A')}")
        
        breakdown = underwriting.get("breakdown", {})
        if breakdown:
            print("\nPremium Breakdown:")
            for key, value in breakdown.items():
                if isinstance(value, (int, float)):
                    print(f"  {key}: UGX {value:,.2f}")
                else:
                    print(f"  {key}: {value}")
        
        print("\n" + "="*70)
        print("✅ Motor Private quotation/underwriting integration working!")
        print("="*70 + "\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error generating quotation: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_motor_private_quotation())
    sys.exit(0 if success else 1)
