import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from src.chatbot.dependencies import api_key_protection  # noqa: E402
from src.chatbot.flows.personal_accident import PersonalAccidentFlow  # noqa: E402
from src.chatbot.flows.serenicare import SerenicareFlow  # noqa: E402
from src.chatbot.flows.motor_private import MotorPrivateFlow  # noqa: E402


class DummyQuote:
    def __init__(self):
        self.id = "Q123"
        from datetime import datetime, timedelta

        self.valid_until = datetime.now() + timedelta(days=30)


class DummyDB:
    def get_user_by_id(self, user_id):
        class User:
            kyc_completed = True

        return User()

    def create_quote(self, **kwargs):
        return DummyQuote()


@pytest.mark.asyncio
async def test_personal_accident_underwriting():
    db = DummyDB()
    flow = PersonalAccidentFlow(None, db)
    collected_data = {
        "personal_details": {
            "first_name": "John",
            "surname": "Doe",
            "date_of_birth": "1980-01-01",
            "gender": "Male",
            "occupation": "Engineer",
            "email": "john@example.com",
        },
        "next_of_kin": {"first_name": "Jane"},
        "coverage_plan": {"sum_assured": 10000000},
    }
    result = await flow.complete_flow(collected_data, "user123")
    print("Personal Accident underwriting result:", result)
    assert (
        ("risk_score" in result)
        or (result.get("status") in ("ok", "review", "success", "declined", "incomplete"))
    )


@pytest.mark.asyncio
async def test_serenicare_underwriting():
    db = DummyDB()
    flow = SerenicareFlow(None, db)
    collected_data = {
        "about_you": {"first_name": "Alice", "surname": "Smith", "email": "alice@example.com"},
        "cover_personalization": {"date_of_birth": "1990-01-01"},
        "medical_conditions": {"has_condition": "no"},
    }
    result = await flow.complete_flow(collected_data, "user456")
    print("Serenicare underwriting result:", result)
    assert (
        ("risk_score" in result)
        or (result.get("status") in ("ok", "review", "success", "declined", "incomplete"))
    )


@pytest.mark.asyncio
async def test_motor_private_underwriting():
    db = DummyDB()
    flow = MotorPrivateFlow(None, db)
    collected_data = {
        "about_you": {"first_name": "Bob", "surname": "Brown", "email": "bob@example.com"},
        "vehicle_details": {"vehicle_value": 20000000},
    }
    result = await flow.complete_flow(collected_data, "user789")
    print("Motor Private underwriting result:", result)
    assert (
        ("risk_score" in result)
        or (result.get("status") in ("ok", "review", "success", "declined", "incomplete"))
    )


@pytest.mark.asyncio
async def test_api_key_protection_allows_valid_key():
    prev = os.environ.get("API_KEYS")
    os.environ["API_KEYS"] = "k1,k2"
    try:
        await api_key_protection(x_api_key="k1")      # should not raise
        await api_key_protection(x_api_key="  k1  ")  # should not raise (whitespace tolerance)
    finally:
        if prev is None:
            os.environ.pop("API_KEYS", None)
        else:
            os.environ["API_KEYS"] = prev


@pytest.mark.asyncio
async def test_api_key_protection_rejects_missing_or_invalid_key():
    prev = os.environ.get("API_KEYS")
    os.environ["API_KEYS"] = "k1,k2"
    try:
        with pytest.raises(HTTPException) as exc:
            await api_key_protection(x_api_key=None)
        assert exc.value.status_code == 401

        with pytest.raises(HTTPException) as exc2:
            await api_key_protection(x_api_key="bad")
        assert exc2.value.status_code == 401
    finally:
        if prev is None:
            os.environ.pop("API_KEYS", None)
        else:
            os.environ["API_KEYS"] = prev
