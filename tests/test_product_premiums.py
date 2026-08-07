"""Tests for product-specific underwriting and premium logic (Personal Accident, Motor Private, Serenicare)."""

import pytest

from src.chatbot.flows.personal_accident import PERSONAL_ACCIDENT_COVERAGE_PLANS, PersonalAccidentFlow
from src.chatbot.flows.motor_private import MotorPrivateFlow
from src.chatbot.flows.serenicare import SERENICARE_PLANS, SerenicareFlow


# --- Personal Accident ---


@pytest.fixture
def pa_flow(db):
    return PersonalAccidentFlow(product_catalog={}, db=db)


def test_pa_premium_base(pa_flow):
    """Personal Accident base premium (no risky activities)."""
    data = {"risky_activities": {"selected": []}}
    plan = PERSONAL_ACCIDENT_COVERAGE_PLANS[0]
    sum_assured = plan["sum_assured"]
    result = pa_flow._calculate_pa_premium(data, sum_assured)
    assert "annual" in result
    assert "monthly" in result
    assert "breakdown" in result
    assert result["monthly"] > 0
    assert result["annual"] > 0
    assert abs(result["annual"] - (result["monthly"] * 12)) < 0.1


def test_pa_premium_with_risky_activities(pa_flow):
    """Personal Accident premium increases with risky activities loading."""
    data_no_risk = {"risky_activities": {"selected": []}}
    data_risk = {"risky_activities": {"selected": ["mining"]}}
    plan = PERSONAL_ACCIDENT_COVERAGE_PLANS[1]
    sum_assured = plan["sum_assured"]
    base = pa_flow._calculate_pa_premium(data_no_risk, sum_assured)
    with_loading = pa_flow._calculate_pa_premium(data_risk, sum_assured)
    assert with_loading["annual"] > base["annual"]
    assert with_loading["breakdown"].get("loadings")


def test_pa_premium_different_sum_assured(pa_flow):
    """Higher sum assured gives higher premium."""
    data = {"risky_activities": {"selected": []}}
    low = pa_flow._calculate_pa_premium(data, 10_000_000)
    high = pa_flow._calculate_pa_premium(data, 50_000_000)
    assert high["monthly"] > low["monthly"]


# --- Motor Private ---


@pytest.fixture
def motor_flow(db):
    return MotorPrivateFlow(product_catalog={}, db=db)


def test_motor_private_premium(motor_flow):
    """Motor Private returns fixed breakdown (base, levy, vat, etc.)."""
    data = {}
    result = motor_flow._calculate_motor_private_premium(data)
    assert "base_premium" in result
    assert "training_levy" in result
    assert "sticker_fees" in result
    assert "vat" in result
    assert "stamp_duty" in result
    assert "total" in result
    total = result["total"]
    expected = (
        result["base_premium"] + result["training_levy"] + result["sticker_fees"] + result["vat"] + result["stamp_duty"]
    )
    assert abs(total - expected) < 0.01


# --- Serenicare ---


@pytest.fixture
def serenicare_flow(db):
    return SerenicareFlow(product_catalog={}, db=db)


def test_serenicare_premium_essential(serenicare_flow):
    """Serenicare Essential plan base premium."""
    plan = next(p for p in SERENICARE_PLANS if p["id"] == "essential")
    data = {"optional_benefits": []}
    result = serenicare_flow._calculate_serenicare_premium(data, plan)
    assert result["monthly"] > 0
    assert result["annual"] == result["monthly"] * 12
    assert "breakdown" in result


def test_serenicare_premium_by_plan(serenicare_flow):
    """Higher plan tier has higher premium."""
    data = {"optional_benefits": []}
    essential = serenicare_flow._calculate_serenicare_premium(data, next(p for p in SERENICARE_PLANS if p["id"] == "essential"))
    premium_tier = serenicare_flow._calculate_serenicare_premium(data, next(p for p in SERENICARE_PLANS if p["id"] == "premium"))
    assert premium_tier["monthly"] > essential["monthly"]


def test_serenicare_premium_optional_benefits(serenicare_flow):
    """Optional benefits add to premium."""
    plan = next(p for p in SERENICARE_PLANS if p["id"] == "classic")
    data_base = {"optional_benefits": []}
    data_with_opts = {"optional_benefits": ["outpatient", "dental"]}
    base = serenicare_flow._calculate_serenicare_premium(data_base, plan)
    with_opts = serenicare_flow._calculate_serenicare_premium(data_with_opts, plan)
    assert with_opts["annual"] > base["annual"]
    benefit_breakdown = with_opts["breakdown"].get("benefit_breakdown", {})
    assert "Outpatient" in benefit_breakdown
    assert "Dental Cover" in benefit_breakdown
