import json

import pytest

from src.integrations.clients.mocks.underwriting_mocks.underwriting import MockUnderwritingClient


@pytest.mark.asyncio
async def test_serenicare_mock_is_product_specific_and_persisted(tmp_path):
    client = MockUnderwritingClient(output_root=tmp_path)

    payload = {
        "product_id": "serenicare",
        "plan_option": {"id": "premium"},
        "medical_conditions": ["hypertension"],
        "optional_benefits": ["Dental"],
    }

    result = await client.create_quote(payload)

    assert result["decision_status"] == "APPROVED"
    assert result["product_mock"] == "serenicare"
    assert result["premium"] > 0

    written_files = list((tmp_path / "serenicare").glob("*.json"))
    assert len(written_files) == 1

    body = json.loads(written_files[0].read_text(encoding="utf-8"))
    assert body["product_id"] == "serenicare"
    assert body["output"]["decision_status"] == "APPROVED"


@pytest.mark.asyncio
async def test_personal_accident_mock_applies_risk_loading_and_requirements(tmp_path):
    client = MockUnderwritingClient(output_root=tmp_path)

    payload = {
        "product_id": "personal_accident",
        "coverLimitAmountUgx": 50_000_000,
        "dob": "1995-06-10",
        "riskyActivities": ["bungee_jumping"],
    }

    result = await client.submit_underwriting(payload)

    assert result["product_mock"] == "personal_accident"
    assert result["decision_status"] == "REFERRED"
    assert pytest.approx(result["premium"], rel=1e-6) == 90750.0
    assert any(
        item["type"] == "underwriting" and "Cover limit" in item["message"]
        for item in result["requirements"]
    )
    assert all(set(item.keys()) == {"type", "message"} for item in result["requirements"])

    written_files = list((tmp_path / "personal_accident").glob("*.json"))
    assert len(written_files) == 1


@pytest.mark.asyncio
async def test_personal_accident_declines_when_cover_missing_or_invalid(tmp_path):
    client = MockUnderwritingClient(output_root=tmp_path)

    payload = {
        "product_id": "personal_accident",
        "dob": "1992-01-01",
        "riskyActivities": [],
    }

    result = await client.create_quote(payload)

    assert result["decision_status"] == "APPROVED"
    assert result["premium"] > 0.0
    assert result["requirements"] == []


@pytest.mark.asyncio
async def test_personal_accident_declines_for_underage_applicant(tmp_path):
    client = MockUnderwritingClient(output_root=tmp_path)

    payload = {
        "product_id": "personal_accident",
        "coverLimitAmountUgx": 10_000_000,
        "dob": "2010-05-01",
        "riskyActivities": [],
    }

    result = await client.create_quote(payload)

    assert result["decision_status"] == "REFERRED"
    assert any(
        req["type"] == "underwriting" and "at least 18 years old" in req["message"]
        for req in result["requirements"]
    )


@pytest.mark.asyncio
async def test_personal_accident_refers_for_high_cover_manual_review(tmp_path):
    client = MockUnderwritingClient(output_root=tmp_path)

    payload = {
        "product_id": "personal_accident",
        "coverLimitAmountUgx": 250_000_000,
        "dob": "1990-01-01",
        "riskyActivities": [],
    }

    result = await client.create_quote(payload)

    assert result["decision_status"] == "REFERRED"
    assert any(
        req["type"] == "underwriting" and "Cover limit" in req["message"]
        for req in result["requirements"]
    )


@pytest.mark.asyncio
async def test_personal_accident_approved_uses_age_modifier_and_decimal_rounding(tmp_path):
    client = MockUnderwritingClient(output_root=tmp_path)

    payload = {
        "product_id": "personal_accident",
        "coverLimitAmountUgx": 50_000_000,
        "dob": "1993-08-15",
        "riskyActivities": [],
    }

    result = await client.create_quote(payload)

    assert result["decision_status"] == "REFERRED"
    assert pytest.approx(result["premium"], rel=1e-6) == 90750.0
    assert result["breakdown"]["base_premium"] == 75000.0
    assert result["breakdown"]["annual_total"] == 90750.0
    assert result["breakdown"]["monthly_total"] == 7562.5


@pytest.mark.asyncio
async def test_unknown_product_uses_general_mock_and_folder(tmp_path):
    client = MockUnderwritingClient(output_root=tmp_path)

    result = await client.create_quote({"foo": "bar"})

    assert result["product_mock"] == "general"
    assert result["decision_status"] == "approved"

    written_files = list((tmp_path / "general").glob("*.json"))
    assert len(written_files) == 1


@pytest.mark.asyncio
async def test_travel_insurance_mock_is_product_specific_and_persisted(tmp_path):
    client = MockUnderwritingClient(output_root=tmp_path)

    payload = {
        "product_id": "travel",
        "travelStartDate": "2026-04-10",
        "travelEndDate": "2026-04-16",
        "coverLevel": "worldwide_essential",
        "travellers": [{"dob": "1990-01-01"}],
    }

    result = await client.create_quote(payload)

    assert result["product_mock"] == "travel_insurance"
    assert result["decision_status"] == "APPROVED"
    assert result["premium"] > 0

    written_files = list((tmp_path / "travel_insurance").glob("*.json"))
    assert len(written_files) == 1


@pytest.mark.asyncio
async def test_motor_private_mock_refers_high_value_vehicle_and_persists(tmp_path):
    client = MockUnderwritingClient(output_root=tmp_path)

    payload = {
        "product_id": "motor_private",
        "vehicle_value_ugx": 180_000_000,
        "car_usage_region": "Outside East Africa",
        "year_of_manufacture": 2010,
    }

    result = await client.submit_underwriting(payload)

    assert result["product_mock"] == "motor_private"
    assert result["decision_status"] == "REFERRED"
    assert result["premium"] > 0
    assert any(item["field"] == "vehicle_value_ugx" for item in result["requirements"])

    written_files = list((tmp_path / "motor_private").glob("*.json"))
    assert len(written_files) == 1
