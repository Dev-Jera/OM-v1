from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.chatbot.flows.serenicare import SerenicareFlow


def _make_mock_db():
    quotes = []

    def create_quote(**kwargs):
        quote = SimpleNamespace(
            id="mock-serenicare-quote-1",
            premium_amount=kwargs.get("premium_amount", 0),
            product_id=kwargs.get("product_id", "serenicare"),
            product_name=kwargs.get("product_name", "Serenicare"),
        )
        quotes.append(quote)
        return quote

    db = MagicMock()
    db.create_quote = create_quote
    return db


@pytest.fixture
def flow():
    test_flow = SerenicareFlow(product_catalog=MagicMock(), db=_make_mock_db())
    test_flow.controller = None
    return test_flow


@pytest.mark.asyncio
async def test_serenicare_steps_and_field_order(flow):
    assert SerenicareFlow.STEPS == [
        "about_you",
        "plan_selection",
        "optional_benefits",
        "medical_conditions",
        "cover_personalization",
        "premium_and_download",
        "choose_plan_and_pay",
    ]

    result = await flow.start("user-1", {})
    assert result.get("next_step") == 1
    assert result["response"]["type"] == "form"
    assert [field["name"] for field in result["response"]["fields"]] == [
        "first_name",
        "middle_name",
        "surname",
        "phone_number",
        "email",
    ]

    collected = result["collected_data"]

    result = await flow.process_step(
        {
            "first_name": "Jane",
            "middle_name": "A",
            "surname": "Doe",
            "phone_number": "0772123456",
            "email": "jane@example.com",
        },
        0,
        collected,
        "user-1",
    )
    assert result.get("next_step") == 1
    assert result["collected_data"]["about_you"]["first_name"] == "Jane"

    collected = result["collected_data"]
    result = await flow.process_step({"plan_option": "classic"}, 1, collected, "user-1")
    assert result.get("next_step") == 2
    assert result["response"]["type"] == "options"
    assert result["collected_data"]["plan_option"]["id"] == "classic"

    collected = result["collected_data"]
    result = await flow.process_step({"optional_benefits": ["outpatient", "dental"]}, 2, collected, "user-1")
    assert result.get("next_step") == 3
    assert result["response"]["type"] == "checkbox"
    assert result["collected_data"]["optional_benefits"] == ["outpatient", "dental"]

    collected = result["collected_data"]
    result = await flow.process_step({"has_condition": False}, 3, collected, "user-1")
    assert result.get("next_step") == 4
    assert result["response"]["type"] == "radio"
    assert result["response"]["question_id"] == "medical_conditions"
    assert result["collected_data"]["medical_conditions"]["has_condition"] is False

    collected = result["collected_data"]
    result = await flow.process_step(
        {
            "date_of_birth": "1990-01-01",
            "include_spouse": True,
            "include_children": False,
            "add_another_main_member": False,
            "spouse_dob": "1992-06-14",
        },
        4,
        collected,
        "user-1",
    )
    assert result.get("next_step") == 5
    assert result["response"]["type"] == "form"
    assert [field["name"] for field in result["response"]["fields"]] == [
        "date_of_birth",
        "include_spouse",
        "spouse_dob",
        "include_children",
        "child_dob",
        "add_another_main_member",
        "other_member_dob",
    ]

    collected = result["collected_data"]
    result = await flow.process_step({}, 5, collected, "user-1")
    assert result.get("next_step") == 6
    assert result["response"]["type"] == "premium_summary"
    assert result["response"]["quote_id"]
    assert result["response"]["download_url"]

    collected = result["collected_data"]
    result = await flow.process_step({"action": "proceed_to_pay"}, 6, collected, "user-1")
    assert result.get("complete") is True
    assert result.get("next_flow") == "payment"
    assert result["response"]["type"] == "proceed_to_payment"
    assert result["response"]["quote_id"]
