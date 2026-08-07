from __future__ import annotations

from src.integrations.clients.mocks.product_logic.personal_accident_insurance import (
    PersonalAccidentPremiumService,
    build_quotation,
    generate_quote_pdf,
)


def _sample_flow_data():
    return {
        "quick_quote": {
            "first_name": "Jane",
            "middle_name": "A",
            "last_name": "Doe",
            "email": "jane@example.com",
            "mobile": "0772123456",
            "dob": "1990-01-01",
            "policy_start_date": "2026-04-01",
            "cover_limit_ugx": 10_000_000,
        },
        "personal_details": {
            "occupation": "Engineer",
            "gender": "Female",
            "nationality": "Ugandan",
            "national_id_number": "CF1234567890AB",
        },
        "next_of_kin": {
            "nok_first_name": "John",
            "nok_last_name": "Doe",
            "nok_relationship": "Brother",
            "nok_phone_number": "0772111111",
            "nok_address": "Kampala",
        },
        "risky_activities": {"selected": ["mining"]},
        "physical_disability": {"free_from_disability": True},
        "previous_pa_policy": {"had_policy": False},
    }


def test_personal_accident_quote_builder_returns_complete_payload():
    quotation = build_quotation(_sample_flow_data(), "PA-QUOTE-1")

    assert quotation["quote_number"] == "PA-QUOTE-1"
    assert quotation["product"] == "Personal Accident Insurance"
    assert quotation["pricing"]["annual"] > 0
    assert quotation["pricing"]["monthly"] > 0
    assert quotation["underwriting"]["decision"] in {"accept", "refer", "decline"}


def test_personal_accident_quote_pdf_generator_returns_pdf_bytes():
    quotation = build_quotation(_sample_flow_data(), "PA-QUOTE-2")
    pdf_bytes = generate_quote_pdf(quotation)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500


def test_personal_accident_premium_service_shim_exposes_expected_methods():
    service = PersonalAccidentPremiumService()
    pricing = service.calculate_sync("personal_accident", {"data": _sample_flow_data(), "sum_assured": 10_000_000})
    pdf_bytes = service.generate_pdf_sync(_sample_flow_data(), "PA-QUOTE-3")

    assert pricing["annual"] > 0
    assert pricing["monthly"] > 0
    assert pdf_bytes.startswith(b"%PDF")
