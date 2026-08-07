#!/usr/bin/env python3
"""
Quick test to verify motor_private dynamic benefits loading
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.integrations.product_benefits import product_benefits_loader


def test_motor_private_benefits():
    """Test that motor_private benefits can be loaded dynamically"""
    print("\n" + "="*70)
    print("Testing Motor Private Benefits Loading")
    print("="*70)
    
    # Load motor_private benefits
    # For motor_private, we pass 0 since comprehensive coverage has standard benefits
    benefits = product_benefits_loader.get_benefits_as_dict("motor_private", 0)
    
    print(f"\n✅ Successfully loaded {len(benefits)} benefits for Motor Private\n")
    
    # Display the benefits
    for i, benefit in enumerate(benefits, 1):
        label = benefit.get("label", "N/A")
        value = benefit.get("value", "N/A")
        print(f"{i:2d}. {label}: {value}")
    
    # Verify we have the expected number of benefits
    expected_count = 20  # Based on motor_private_config.json comprehensive tier
    assert len(benefits) == expected_count, f"Expected {expected_count} benefits, got {len(benefits)}"
    
    # Verify some key benefits are present
    benefit_labels = [b["label"] for b in benefits]
    key_benefits = [
        "Limit of liability: third party bodily injury per occurrence",
        "Windscreen extension",
        "Personal accident to driver"
    ]
    
    for key_benefit in key_benefits:
        assert any(key_benefit in label for label in benefit_labels), \
            f"Expected benefit '{key_benefit}' not found"
    
    print("\n" + "="*70)
    print("✅ All tests passed!")
    print("="*70 + "\n")


if __name__ == "__main__":
    test_motor_private_benefits()
