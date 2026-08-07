"""Safety checks for premium helper contract stability after service delegation."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional

import pytest

from src.chatbot.flows.motor_private import MotorPrivateFlow
from src.chatbot.flows.personal_accident import PersonalAccidentFlow
from src.chatbot.flows.serenicare import SerenicareFlow
from src.chatbot.flows.travel_insurance import TravelInsuranceFlow


def _pa_baseline(data: Dict[str, Any], sum_assured: int) -> Dict[str, Any]:
    base_rate = Decimal("0.0015")
    annual = Decimal(sum_assured) * base_rate

    breakdown: Dict[str, Any] = {"base_annual": float(annual)}

    dob: Optional[date] = None
    try:
        dob_str = ""
        if isinstance(data, dict):
            dob_str = str(data.get("dob") or "")
            if not dob_str:
                q = data.get("quick_quote") or {}
                dob_str = str((q or {}).get("dob") or "")
        if dob_str:
            dob = date.fromisoformat(dob_str)
    except Exception:
        dob = None

    if dob:
        today = date.today()
        age = today.year - dob.year - (1 if (today.month, today.day) < (dob.month, dob.day) else 0)

        if age < 25:
            modifier = Decimal("1.25")
            loading = annual * (modifier - 1)
            annual += loading
            breakdown["age_loading"] = float(loading)
        elif age > 60:
            modifier = Decimal("1.20")
            loading = annual * (modifier - 1)
            annual += loading
            breakdown["age_loading"] = float(loading)

    risky_selected = []
    if isinstance(data, dict):
        risky = data.get("risky_activities") or {}
        risky_selected = risky.get("selected") or []
    if isinstance(risky_selected, list) and len(risky_selected) > 0:
        loading = annual * Decimal("0.10")
        annual += loading
        breakdown["risky_activities_loading"] = float(loading)

    monthly = annual / 12

    return {
        "annual": float(annual.quantize(Decimal("0.01"))),
        "monthly": float(monthly.quantize(Decimal("0.01"))),
        "breakdown": breakdown,
    }


def _serenicare_baseline(data: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    plan_id = (plan or {}).get("id", "essential")

    base_by_plan = {
        "essential": Decimal("50000"),
        "classic": Decimal("80000"),
        "comprehensive": Decimal("120000"),
        "premium": Decimal("180000"),
    }
    base = base_by_plan.get(plan_id, base_by_plan["essential"])

    optional_prices = {
        "outpatient": Decimal("15000"),
        "maternity": Decimal("20000"),
        "dental": Decimal("8000"),
        "optical": Decimal("7000"),
        "covid19": Decimal("5000"),
    }

    selected = data.get("optional_benefits") or []
    if isinstance(selected, str):
        selected = [s.strip() for s in selected.split(",") if s.strip()]

    breakdown: Dict[str, Any] = {
        "base": float(base),
        "plan_id": plan_id,
    }

    opts_total = Decimal("0")
    for opt in selected:
        if opt in optional_prices:
            breakdown[opt] = float(optional_prices[opt])
            opts_total += optional_prices[opt]

    monthly = base + opts_total
    annual = monthly * 12

    return {
        "monthly": float(monthly),
        "annual": float(annual),
        "breakdown": breakdown,
    }


def _travel_baseline(data: Dict[str, Any]) -> Dict[str, Any]:
    trip = data.get("travel_party_and_trip") or {}
    days = _trip_days(trip.get("departure_date"), trip.get("return_date"))

    travellers_18_69 = int(trip.get("num_travellers_18_69") or 0)
    travellers_0_17 = int(trip.get("num_travellers_0_17") or 0)
    travellers_70_75 = int(trip.get("num_travellers_70_75") or 0)
    travellers_76_80 = int(trip.get("num_travellers_76_80") or 0)
    travellers_81_85 = int(trip.get("num_travellers_81_85") or 0)

    product = data.get("selected_product") or {}
    product_id = product.get("id", "worldwide_essential")

    product_multiplier = {
        "worldwide_essential": Decimal("1.0"),
        "worldwide_elite": Decimal("1.5"),
        "schengen_essential": Decimal("1.2"),
        "schengen_elite": Decimal("1.7"),
        "student_cover": Decimal("0.9"),
        "africa_asia": Decimal("0.8"),
        "inbound_karibu": Decimal("0.6"),
    }.get(product_id, Decimal("1.0"))

    rate_18_69 = Decimal("2.0")
    rate_0_17 = Decimal("1.0")
    rate_70_75 = Decimal("3.0")
    rate_76_80 = Decimal("4.0")
    rate_81_85 = Decimal("5.0")

    base_usd = Decimal(days) * (
        Decimal(travellers_18_69) * rate_18_69
        + Decimal(travellers_0_17) * rate_0_17
        + Decimal(travellers_70_75) * rate_70_75
        + Decimal(travellers_76_80) * rate_76_80
        + Decimal(travellers_81_85) * rate_81_85
    )

    total_usd = (base_usd * product_multiplier).quantize(Decimal("0.01"))
    usd_to_ugx = Decimal("3900")
    total_ugx = (total_usd * usd_to_ugx).quantize(Decimal("1."))

    return {
        "total_usd": float(total_usd),
        "total_ugx": float(total_ugx),
        "breakdown": {
            "days": days,
            "product_id": product_id,
            "product_multiplier": float(product_multiplier),
            "travellers": {
                "18_69": travellers_18_69,
                "0_17": travellers_0_17,
                "70_75": travellers_70_75,
                "76_80": travellers_76_80,
                "81_85": travellers_81_85,
            },
            "base_usd": float(base_usd),
            "usd_to_ugx": float(usd_to_ugx),
        },
    }


def _trip_days(departure_date: Any, return_date: Any) -> int:
    d1 = _safe_iso_date(departure_date)
    d2 = _safe_iso_date(return_date)
    if not d1 or not d2:
        return 1
    return max(1, (d2 - d1).days + 1)


def _safe_iso_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return None


def _motor_baseline() -> Dict[str, Any]:
    base_premium = Decimal("1280000")
    training_levy = Decimal("6400")
    sticker_fees = Decimal("6000")
    vat = Decimal("232632")
    stamp_duty = Decimal("35000")
    total = base_premium + training_levy + sticker_fees + vat + stamp_duty
    return {
        "base_premium": float(base_premium),
        "training_levy": float(training_levy),
        "sticker_fees": float(sticker_fees),
        "vat": float(vat),
        "stamp_duty": float(stamp_duty),
        "total": float(total),
    }


def test_pa_helper_contract_unchanged(db):
    flow = PersonalAccidentFlow(product_catalog={}, db=db)
    data = {"quick_quote": {"dob": "1990-01-01"}, "risky_activities": {"selected": ["mining"]}}
    actual = flow._calculate_pa_premium(data, 10_000_000)
    assert {"annual", "monthly", "breakdown", "total"}.issubset(actual.keys())
    assert actual["annual"] == actual["total"]
    assert abs(actual["annual"] - (actual["monthly"] * 12)) < 0.1
    assert "loadings" in actual["breakdown"]


def test_serenicare_helper_contract_unchanged(db):
    flow = SerenicareFlow(product_catalog={}, db=db)
    data = {"optional_benefits": ["outpatient", "dental"]}
    plan = {"id": "classic"}
    actual = flow._calculate_serenicare_premium(data, plan)
    assert {"monthly", "annual", "breakdown", "benefit_breakdown"}.issubset(actual.keys())
    assert "Outpatient" in actual["benefit_breakdown"]
    assert "Dental Cover" in actual["benefit_breakdown"]


def test_travel_helper_contract_unchanged(db, monkeypatch):
    monkeypatch.setattr(
        "src.integrations.clients.real_http.travel_quote_generator.generate_travel_quote",
        lambda _payload: {"benefits": "API benefits", "benefitsUrl": "https://example.com/travel.pdf"},
    )

    flow = TravelInsuranceFlow(product_catalog={}, db=db)
    data = {
        "selected_product": {"id": "worldwide_essential"},
        "priceInclTax": 55.0,
        "travel_party_and_trip": {
            "departure_date": "2026-03-03",
            "return_date": "2026-03-08",
            "num_travellers_18_69": 1,
        },
    }
    actual = flow._calculate_travel_premium(data)
    assert {"total_usd", "total_ugx", "breakdown", "total", "monthly", "annual"}.issubset(actual.keys())
    assert actual["total_usd"] > 0
    assert actual["total_ugx"] > 0
    assert actual["breakdown"]["days"] == 6
    assert actual["breakdown"]["benefits"] == "API benefits"


def test_motor_helper_contract_unchanged(db):
    flow = MotorPrivateFlow(product_catalog={}, db=db)
    actual = flow._calculate_motor_private_premium({})
    assert {
        "base_premium",
        "training_levy",
        "sticker_fee",
        "vat",
        "stamp_duty",
        "total",
    }.issubset(actual.keys())


@pytest.mark.asyncio
async def test_mock_premium_endpoint_client_shape_and_artifact(tmp_path):
    from src.integrations.clients.mocks.premium_mocks.premium import MockPremiumClient

    client = MockPremiumClient(output_root=tmp_path)
    result = await client.calculate_premium("motor_private", {"data": {}})

    assert {
        "base_premium",
        "training_levy",
        "sticker_fee",
        "vat",
        "stamp_duty",
        "total",
        "mock_output_path",
    }.issubset(result.keys())
    assert (tmp_path / "motor_private").exists()
