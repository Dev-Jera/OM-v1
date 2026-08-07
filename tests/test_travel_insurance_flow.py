"""
Tests for the Travel Insurance flow.

Run with: pytest tests/test_travel_insurance_flow.py -v
Or: python -m pytest tests/test_travel_insurance_flow.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.chatbot.flows.travel_insurance import (
    TRAVEL_INSURANCE_PRODUCTS,
    TRAVEL_INSURANCE_BENEFITS,
    TravelInsuranceFlow,
)


def _make_mock_db():
    """Create a mock DB that tracks created quotes."""
    quotes = []

    def create_quote(**kwargs):
        q = SimpleNamespace(
            id="mock-quote-123",
            premium_amount=kwargs.get("premium_amount", 0),
            product_id=kwargs.get("product_id", "travel_insurance"),
            product_name=kwargs.get("product_name", "Travel Insurance"),
        )
        quotes.append(q)
        return q

    def get_quote(quote_id):
        return next((q for q in quotes if str(q.id) == str(quote_id)), None)

    db = MagicMock()
    db.create_quote = create_quote
    db.get_quote = get_quote
    return db


@pytest.fixture
def flow():
    db = _make_mock_db()
    return TravelInsuranceFlow(product_catalog=MagicMock(), db=db)


@pytest.mark.asyncio
async def test_flow_steps_defined(flow):
    """Travel insurance flow has expected step names."""
    assert len(TravelInsuranceFlow.STEPS) == 9
    assert TravelInsuranceFlow.STEPS[0] == "about_you"
    assert TravelInsuranceFlow.STEPS[1] == "product_selection"
    assert "about_you" in TravelInsuranceFlow.STEPS
    assert "travel_party_and_trip" in TravelInsuranceFlow.STEPS
    assert "data_consent" in TravelInsuranceFlow.STEPS
    assert "traveller_details" in TravelInsuranceFlow.STEPS
    assert "emergency_contact" in TravelInsuranceFlow.STEPS
    assert "premium_summary" in TravelInsuranceFlow.STEPS
    assert "choose_plan_and_pay" in TravelInsuranceFlow.STEPS


@pytest.mark.asyncio
async def test_start_returns_about_you(flow):
    """Starting the flow returns about you step."""
    result = await flow.start("user-1", {})
    assert "response" in result
    resp = result["response"]
    assert resp.get("type") == "form"
    fields = resp.get("fields", [])
    names = [f["name"] for f in fields]
    assert "first_name" in names
    assert "surname" in names


@pytest.mark.asyncio
async def test_product_selection_step(flow):
    """Step 1: Product selection returns product cards with a default selection."""
    result = await flow.process_step({}, 1, {}, "user-1")
    assert result.get("next_step") == 1
    assert result["response"]["type"] == "product_cards"
    assert len(result["response"]["products"]) == 7
    assert any(p.get("selected") for p in result["response"]["products"])
    assert result["collected_data"]["selected_product"]["id"] == TRAVEL_INSURANCE_PRODUCTS[0]["id"]


@pytest.mark.asyncio
async def test_about_you_step(flow):
    """Step 0: About you form has required fields."""
    result = await flow.process_step({}, 0, {}, "user-1")
    assert result.get("next_step") == 0
    assert result["response"]["type"] == "form"
    fields = result["response"]["fields"]
    names = [f["name"] for f in fields]
    assert "first_name" in names
    assert "surname" in names
    assert "email" in names
    assert "phone_number" in names


@pytest.mark.asyncio
async def test_about_you_stores_data(flow):
    """Step 0: About you stores submitted data."""
    form_data = {
        "first_name": "Jane",
        "surname": "Doe",
        "email": "jane@example.com",
        "phone_number": "0772123456",
    }
    data = {}
    await flow._step_about_you(form_data, data, "user-1")
    assert "about_you" in data
    assert data["about_you"]["first_name"] == "Jane"
    assert data["about_you"]["surname"] == "Doe"


@pytest.mark.asyncio
async def test_travel_party_step(flow):
    """Step 2: Travel party and trip form."""
    result = await flow.process_step({}, 2, {}, "user-1")
    assert result.get("next_step") == 2
    fields = result["response"]["fields"]
    names = [f["name"] for f in fields]
    assert "travel_party" in names
    assert "departure_country" in names
    assert "destination_country" in names
    assert "departure_date" in names
    assert "return_date" in names


@pytest.mark.asyncio
async def test_data_consent_step(flow):
    """Step 3: Data consent."""
    result = await flow.process_step({}, 3, {}, "user-1")
    assert result.get("next_step") == 3
    assert result["response"]["type"] == "consent"
    assert "consents" in result["response"]


@pytest.mark.asyncio
async def test_premium_calculation(flow, monkeypatch):
    """Premium is calculated correctly for a simple trip."""
    monkeypatch.setattr(
        "src.integrations.clients.real_http.travel_quote_generator.generate_travel_quote",
        lambda _payload: {"benefits": "API benefits", "benefitsUrl": "https://example.com/travel.pdf"},
    )

    data = {
        "selected_product": TRAVEL_INSURANCE_PRODUCTS[0],
        "priceInclTax": 50.0,
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
    assert "total_usd" in premium
    assert "total_ugx" in premium
    assert premium["total_usd"] > 0
    assert premium["total_ugx"] > 0
    assert premium["breakdown"]["days"] == 6
    assert premium["breakdown"]["benefits"] == "API benefits"


@pytest.mark.asyncio
async def test_full_flow_to_payment(flow, monkeypatch):
    """Walk through flow with minimal data to reach payment step."""
    monkeypatch.setattr(
        "src.integrations.clients.real_http.travel_quote_generator.generate_travel_quote",
        lambda _payload: {"benefits": "API benefits", "benefitsUrl": "https://example.com/travel.pdf"},
    )

    data = {
        "user_id": "user-1",
        "product_id": "travel_insurance",
        "selected_product": TRAVEL_INSURANCE_PRODUCTS[0],
        "priceInclTax": 50.0,
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
            "first_name": "J", "surname": "D", "passport_number": "1234567890",
            "nationality_type": "ugandan", "occupation": "Engineer",
            "phone_number": "0772111111", "email": "j@x.com",
            "postal_address": "Kampala", "town_city": "Kampala",
        }],
        "emergency_contact": {"ec_surname": "X", "ec_relationship": "Spouse", "ec_phone_number": "0772222222", "ec_email": "x@x.com"},
        "passport_upload": {"file_ref": "mock-file-ref"},
    }

    # Step 8: choose_plan_and_pay with "proceed"
    result = await flow.process_step({"action": "proceed"}, 8, data, "user-1")

    assert result.get("complete") is True
    assert result.get("next_flow") == "payment"
    assert "quote_id" in result.get("data", {})


@pytest.mark.asyncio
async def test_benefits_defined():
    """Benefits list is non-empty."""
    assert len(TRAVEL_INSURANCE_BENEFITS) >= 5
    assert any("medical" in b["benefit"].lower() for b in TRAVEL_INSURANCE_BENEFITS)


@pytest.mark.asyncio
async def test_products_have_ids():
    """All products have id, label, description."""
    for p in TRAVEL_INSURANCE_PRODUCTS:
        assert "id" in p
        assert "label" in p
        assert "description" in p
