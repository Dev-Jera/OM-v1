import pytest
from datetime import date, timedelta

from src.chatbot.flows.dynamic_question_engine import DynamicQuestionEngineFlow


class DummyQuote:
    def __init__(self):
        self.id = "Q-1"
        from datetime import datetime, timedelta

        self.valid_until = datetime.now() + timedelta(days=30)


class DummyDB:
    def get_user_by_id(self, user_id):
        class User:
            kyc_completed = True

        return User()

    def create_quote(self, **kwargs):
        return DummyQuote()


class DummyCatalog:
    def match_products(self, query: str, top_k: int = 3):
        # Mimic ProductMatcher return shape: (score, rank, product_dict)
        return [
            (
                1.0,
                0,
                {
                    "product_id": "website:product:life/sure-deal-savings-plan",
                    "name": "Sure Deal Savings Plan",
                    "category_name": "Save and invest",
                    "sub_category_name": "Savings",
                    "url": "https://www.oldmutual.co.ug/",
                },
            )
        ][:top_k]


@pytest.mark.asyncio
async def test_dynamic_engine_personal_accident_buy_cta():
    flow = DynamicQuestionEngineFlow(product_catalog={}, db=DummyDB())

    started = await flow.start("user-1", {"product_flow": "personal_accident"})
    collected = started["collected_data"]

    start_date = (date.today() + timedelta(days=5)).isoformat()

    # Step 0: quick_quote (frontend field names) now returns premium summary directly.
    out = await flow.process_step(
        {
            "firstName": "John",
            "lastName": "Doe",
            "email": "john@example.com",
            "mobile": "0700000000",
            "dob": "1980-01-01",
            "policyStartDate": start_date,
            "coverLimitAmountUgx": "5000000",
        },
        0,
        collected,
        "user-1",
    )
    resp = out.get("response") or {}
    assert resp.get("type") == "premium_summary"
    action_types = {a.get("type") for a in resp.get("actions", []) if isinstance(a, dict)}
    assert "buy_now" in action_types
    assert "not_now" in action_types

    # Buy -> engine returns buy_cta with quote_id
    out = await flow.process_step({"action": "buy_now"}, 0, out["collected_data"], "user-1")
    assert out.get("complete") is True
    resp = out.get("response") or {}
    assert resp.get("type") == "buy_cta"
    assert resp.get("quote_id")


@pytest.mark.asyncio
async def test_dynamic_engine_personal_accident_canonical_steps_progression():
    flow = DynamicQuestionEngineFlow(product_catalog={}, db=DummyDB())

    started = await flow.start("user-1", {"product_flow": "personal_accident"})
    collected = started["collected_data"]

    start_date = (date.today() + timedelta(days=5)).isoformat()

    # quick_quote now lands on premium_summary
    out = await flow.process_step(
        {
            "firstName": "John",
            "lastName": "Doe",
            "email": "john@example.com",
            "mobile": "0700000000",
            "dob": "1980-01-01",
            "policyStartDate": start_date,
            "coverLimitAmountUgx": "5000000",
        },
        0,
        collected,
        "user-1",
    )
    assert (out.get("response") or {}).get("type") == "premium_summary"
    collected = out["collected_data"]

    # move from premium_summary to personal_details
    out = await flow.process_step({"action": "proceed_to_details"}, 0, collected, "user-1")
    assert (out.get("response") or {}).get("type") == "form"
    collected = out["collected_data"]

    # personal_details
    out = await flow.process_step(
        {
            "surname": "Doe",
            "first_name": "John",
            "email": "john@example.com",
            "mobile_number": "0700000000",
            "national_id_number": "CF123456789012",
            "nationality": "Ugandan",
            "occupation": "Engineer",
            "gender": "Male",
            "country_of_residence": "Uganda",
            "physical_address": "Kampala",
        },
        0,
        collected,
        "user-1",
    )
    assert (out.get("response") or {}).get("type") == "form"
    collected = out["collected_data"]

    # next_of_kin
    out = await flow.process_step(
        {
            "nok_first_name": "Jane",
            "nok_last_name": "Doe",
            "nok_phone_number": "0700000001",
            "nok_relationship": "Spouse",
            "nok_address": "Kampala",
        },
        0,
        collected,
        "user-1",
    )
    assert (out.get("response") or {}).get("type") == "yes_no_details"
    collected = out["collected_data"]

    # previous_pa_policy
    out = await flow.process_step({"had_previous_pa_policy": "no"}, 0, collected, "user-1")
    assert (out.get("response") or {}).get("type") == "yes_no_details"
    collected = out["collected_data"]

    # physical_disability
    out = await flow.process_step({"free_from_disability": "yes"}, 0, collected, "user-1")
    assert (out.get("response") or {}).get("type") == "checkbox"
    collected = out["collected_data"]

    # risky_activities
    out = await flow.process_step({"risky_activities": []}, 0, collected, "user-1")
    assert (out.get("response") or {}).get("type") == "file_upload"
    collected = out["collected_data"]

    # upload_national_id
    out = await flow.process_step({"national_id_file_ref": "file-1"}, 0, collected, "user-1")
    assert (out.get("response") or {}).get("type") == "confirmation"
    collected = out["collected_data"]

    # final_confirmation
    out = await flow.process_step({}, 0, collected, "user-1")
    assert (out.get("response") or {}).get("type") == "confirmation"
    collected = out["collected_data"]

    # final_confirmation -> step complete gets intercepted into buy_cta
    out = await flow.process_step({"action": "confirm"}, 0, collected, "user-1")
    assert (out.get("response") or {}).get("type") == "buy_cta"
    collected = out["collected_data"]

    # buy decision
    out = await flow.process_step({"action": "buy_now"}, 0, collected, "user-1")
    assert out.get("complete") is True
    assert (out.get("response") or {}).get("type") == "buy_cta"


@pytest.mark.asyncio
async def test_dynamic_engine_non_digital_product_info_only():
    flow = DynamicQuestionEngineFlow(product_catalog=DummyCatalog(), db=DummyDB())

    started = await flow.start("user-1", {})
    out = await flow.process_step("Sure Deal Savings Plan", 0, started["collected_data"], "user-1")

    assert out.get("complete") is True
    resp = out.get("response") or {}
    assert resp.get("type") == "info"
