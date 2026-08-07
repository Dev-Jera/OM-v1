#!/usr/bin/env python3
"""
Run Travel Insurance flow tests (no pytest required).

Usage:
  python scripts/run_travel_insurance_tests.py

Or with pytest if available:
  pytest tests/test_travel_insurance_flow.py -v
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import MagicMock
from types import SimpleNamespace

from src.chatbot.flows.travel_insurance import (
    TRAVEL_INSURANCE_PRODUCTS,
    TRAVEL_INSURANCE_BENEFITS,
    TravelInsuranceFlow,
)


def _make_mock_db():
    quotes = []

    def create_quote(**kwargs):
        q = SimpleNamespace(id="mock-quote-123", premium_amount=kwargs.get("premium_amount", 0))
        quotes.append(q)
        return q

    db = MagicMock()
    db.create_quote = create_quote
    db.get_quote = lambda qid: next((q for q in quotes if str(q.id) == str(qid)), None)
    return db


async def run_tests():
    db = _make_mock_db()
    flow = TravelInsuranceFlow(product_catalog=MagicMock(), db=db)
    passed = 0
    failed = 0

    # Test 1: Start returns product selection
    try:
        result = await flow.start("user-1", {})
        assert result.get("response", {}).get("type") == "product_cards"
        assert len(result.get("response", {}).get("products", [])) == 7
        print("[PASS] test_start_returns_product_selection")
        passed += 1
    except Exception as e:
        print(f"[FAIL] test_start_returns_product_selection: {e}")
        failed += 1

    # Test 2: Product selection step
    try:
        result = await flow.process_step({}, 0, {}, "user-1")
        assert result.get("next_step") == 1
        assert result["response"]["type"] == "product_cards"
        print("[PASS] test_product_selection_step")
        passed += 1
    except Exception as e:
        print(f"[FAIL] test_product_selection_step: {e}")
        failed += 1

    # Test 3: About you stores data
    try:
        form_data = {"first_name": "Jane", "surname": "Doe", "email": "j@x.com", "phone_number": "0772111111"}
        data = {}
        await flow._step_about_you(form_data, data, "user-1")
        assert data.get("about_you", {}).get("first_name") == "Jane"
        print("[PASS] test_about_you_stores_data")
        passed += 1
    except Exception as e:
        print(f"[FAIL] test_about_you_stores_data: {e}")
        failed += 1

    # Test 4: Premium calculation
    try:
        data = {
            "selected_product": TRAVEL_INSURANCE_PRODUCTS[0],
            "travel_party_and_trip": {
                "num_travellers_18_69": 1,
                "num_travellers_0_17": 0,
                "num_travellers_70_75": 0,
                "num_travellers_76_80": 0,
                "num_travellers_81_85": 0,
                "departure_date": "2026-03-03",
                "return_date": "2026-03-08",
            },
        }
        premium = flow._calculate_travel_premium(data)
        assert premium["total_usd"] > 0
        assert premium["total_ugx"] > 0
        print("[PASS] test_premium_calculation")
        passed += 1
    except Exception as e:
        print(f"[FAIL] test_premium_calculation: {e}")
        failed += 1

    # Test 5: Full flow to payment
    try:
        data = {
            "user_id": "user-1",
            "product_id": "travel_insurance",
            "selected_product": TRAVEL_INSURANCE_PRODUCTS[0],
            "about_you": {"first_name": "J", "surname": "D", "email": "j@x.com", "phone_number": "0772111111"},
            "travel_party_and_trip": {
                "travel_party": "myself_only",
                "num_travellers_18_69": 1,
                "num_travellers_0_17": 0,
                "num_travellers_70_75": 0,
                "num_travellers_76_80": 0,
                "num_travellers_81_85": 0,
                "departure_country": "Uganda",
                "destination_country": "Portugal",
                "departure_date": "2026-03-03",
                "return_date": "2026-03-08",
            },
            "data_consent": {"terms_and_conditions_agreed": True, "consent_data_outside_uganda": True},
            "travellers": [{
                "first_name": "J", "surname": "D", "passport_number": "AB123",
                "nationality_type": "ugandan", "occupation": "Engineer",
                "phone_number": "0772111111", "email": "j@x.com",
                "postal_address": "Kampala", "town_city": "Kampala",
            }],
            "emergency_contact": {"ec_surname": "X", "ec_relationship": "Spouse", "ec_phone_number": "0772222222", "ec_email": "x@x.com"},
            "passport_upload": {"file_ref": "mock-file-ref"},
        }
        result = await flow.process_step({"action": "proceed"}, 9, data, "user-1")
        assert result.get("complete") is True
        assert result.get("next_flow") == "payment"
        assert "quote_id" in result.get("data", {})
        print("[PASS] test_full_flow_to_payment")
        passed += 1
    except Exception as e:
        print(f"[FAIL] test_full_flow_to_payment: {e}")
        failed += 1

    return passed, failed


def main():
    print("Running Travel Insurance flow tests...\n")
    passed, failed = asyncio.run(run_tests())
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
