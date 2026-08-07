"""Travel Insurance premium mock builder with strict validation.

This mock implementation mirrors frontend validation rules for Travel Sure Plus
and computes premium locally for predictable non-networked testing.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List

from src.chatbot.travel_insurance_countries import DESTINATION_COUNTRIES

_EMAIL_RE = re.compile(r"^\S+@\S+\.\S+$")
_MOBILE_RE = re.compile(r"^(\+2567\d{8}|07\d{8})$")

_COVER_LEVELS = {
    "worldwide_essential",
    "worldwide_elite",
    "schengen_essential",
    "schengen_elite",
    "student_cover",
    "africa_asia",
    "inbound_karibu",
}

_WHO_ARE_YOU_COVERING = {
    "myself",
    "someone_else",
    "myself_and_someone_else",
    "group",
}


def _string(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _field(data: Dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in data:
            return data.get(name)
    return None


def _normalize_mobile(value: str) -> str:
    raw = _string(value).replace(" ", "").replace("-", "")
    if raw.startswith("+2567") and len(raw) == 13:
        return raw
    if raw.startswith("07") and len(raw) == 10:
        return "+256" + raw[1:]
    return raw


def _parse_iso_date(label: str, value: str, errors: Dict[str, str]) -> date | None:
    raw = _string(value)
    if not raw:
        errors[label] = f"{label} is required"
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        errors[label] = f"{label} must be a valid ISO date (YYYY-MM-DD)"
        return None


def _calculate_age(dob: date, today: date) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _age_bucket(age: int) -> str | None:
    if age < 0:
        return None
    if age <= 17:
        return "0_17"
    if age <= 69:
        return "18_69"
    if age <= 75:
        return "70_75"
    if age <= 80:
        return "76_80"
    if age <= 85:
        return "81_85"
    return None


def build_travel_insurance_premium_mock(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate Travel Sure Plus payload and return deterministic premium output.

    Raises ValueError with field-level details when validation fails.
    """
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        raise ValueError("Payload data must be an object")

    errors: Dict[str, str] = {}
    today = date.today()

    first_name = _string(_field(data, "firstName", "first_name"))
    middle_name = _string(_field(data, "middleName", "middle_name"))
    surname = _string(_field(data, "surname", "lastName", "last_name"))
    mobile_raw = _string(_field(data, "mobile", "phone_number"))
    email = _string(_field(data, "email")).lower()

    if len(first_name) < 2 or len(first_name) > 50:
        errors["firstName"] = "First name must be 2–50 characters."
    if middle_name and len(middle_name) > 50:
        errors["middleName"] = "Middle name must be up to 50 characters."
    if len(surname) < 2 or len(surname) > 50:
        errors["surname"] = "Surname must be 2–50 characters."

    mobile_compact = _normalize_mobile(mobile_raw)
    if not _MOBILE_RE.match(mobile_compact if mobile_compact.startswith("0") else mobile_raw.replace("-", "").replace(" ", "")):
        if not _MOBILE_RE.match(mobile_raw.replace("-", "").replace(" ", "")):
            errors["mobile"] = "Mobile number must be in +2567XXXXXXXX, +256 7XXXXXXXX, or 07XXXXXXXX format."

    if (not email) or (len(email) > 100) or (not _EMAIL_RE.match(email)):
        errors["email"] = "Please enter a valid email address."

    cover_level = _string(_field(data, "coverLevel", "cover_level", "product_id", "productId"))
    if cover_level not in _COVER_LEVELS:
        errors["coverLevel"] = "Please select a valid cover level."

    who_covering = _string(_field(data, "whoAreYouCovering", "who_are_you_covering", "travel_party"))
    alias = {
        "myself_only": "myself",
        "myself_and_someone_else": "myself_and_someone_else",
    }
    who_covering = alias.get(who_covering, who_covering)
    if who_covering not in _WHO_ARE_YOU_COVERING:
        errors["whoAreYouCovering"] = "Please select who is being covered."

    destination = _field(data, "destinationCountries", "destination_country", "destinationCountry")
    if isinstance(destination, list):
        destination_value = _string(destination[0]) if destination else ""
    else:
        destination_value = _string(destination)
    if destination_value not in DESTINATION_COUNTRIES:
        errors["destinationCountries"] = "Please select a valid destination country."

    start_date = _parse_iso_date("travelStartDate", _string(_field(data, "travelStartDate", "departure_date", "travel_start_date")), errors)
    end_date = _parse_iso_date("travelEndDate", _string(_field(data, "travelEndDate", "return_date", "travel_end_date")), errors)

    if start_date and start_date < (today.fromordinal(today.toordinal() + 1)):
        errors["travelStartDate"] = "travelStartDate must be on or after tomorrow."
    if end_date and end_date < today:
        errors["travelEndDate"] = "travelEndDate cannot be in the past."
    if start_date and end_date and end_date < start_date:
        errors["travelEndDate"] = "travelEndDate must be on or after travelStartDate."

    travellers_input = _field(data, "travellers")
    travellers: List[Dict[str, str]] = []
    if isinstance(travellers_input, list):
        travellers = [item for item in travellers_input if isinstance(item, dict)]
    elif travellers_input is not None:
        errors["travellers"] = "travellers must be an array of objects."

    if not travellers:
        traveller_dob = _string(_field(data, "travellerDob", "traveller_1_date_of_birth"))
        if traveller_dob:
            travellers = [{"dob": traveller_dob}]

    if who_covering in {"myself", "someone_else"} and len(travellers) != 1:
        errors["travellers"] = "Exactly one traveller is required for this coverage mode."
    if who_covering in {"group", "myself_and_someone_else"} and len(travellers) < 1:
        errors["travellers"] = "At least one traveller is required for this coverage mode."

    age_counts = {"0_17": 0, "18_69": 0, "70_75": 0, "76_80": 0, "81_85": 0}
    for index, traveller in enumerate(travellers):
        dob_raw = _string(traveller.get("dob") or traveller.get("date_of_birth"))
        if not dob_raw:
            errors[f"travellers[{index}].dob"] = "Traveller DOB is required."
            continue
        try:
            dob = date.fromisoformat(dob_raw)
        except ValueError:
            errors[f"travellers[{index}].dob"] = "Traveller DOB must be ISO date (YYYY-MM-DD)."
            continue
        if dob > today:
            errors[f"travellers[{index}].dob"] = "Traveller DOB cannot be in the future."
            continue
        bucket = _age_bucket(_calculate_age(dob, today))
        if not bucket:
            errors[f"travellers[{index}].dob"] = "Traveller age must be between 0 and 85 years."
            continue
        age_counts[bucket] += 1

    if errors:
        formatted = "; ".join([f"{key}: {msg}" for key, msg in errors.items()])
        raise ValueError(formatted)

    duration_days = (end_date - start_date).days + 1  # inclusive
    number_of_travellers = len(travellers)

    product_multiplier = {
        "worldwide_essential": Decimal("1.0"),
        "worldwide_elite": Decimal("1.5"),
        "schengen_essential": Decimal("1.2"),
        "schengen_elite": Decimal("1.7"),
        "student_cover": Decimal("0.9"),
        "africa_asia": Decimal("0.8"),
        "inbound_karibu": Decimal("0.6"),
    }[cover_level]

    base_usd = Decimal(duration_days) * (
        Decimal(age_counts["18_69"]) * Decimal("2.0")
        + Decimal(age_counts["0_17"]) * Decimal("1.0")
        + Decimal(age_counts["70_75"]) * Decimal("3.0")
        + Decimal(age_counts["76_80"]) * Decimal("4.0")
        + Decimal(age_counts["81_85"]) * Decimal("5.0")
    )
    total_usd = (base_usd * product_multiplier).quantize(Decimal("0.01"))
    usd_to_ugx = Decimal("3900")
    total_ugx = (total_usd * usd_to_ugx).quantize(Decimal("1."))

    return {
        "total_usd": float(total_usd),
        "total_ugx": float(total_ugx),
        "breakdown": {
            "coverLevel": cover_level,
            "whoAreYouCovering": who_covering,
            "departureCountry": "Uganda",
            "destinationCountries": destination_value,
            "travelStartDate": start_date.isoformat(),
            "travelEndDate": end_date.isoformat(),
            "durationOfTravel": duration_days,
            "numberOfTravellers": number_of_travellers,
            "travellers": [{"dob": _string(t.get("dob") or t.get("date_of_birth"))} for t in travellers],
            "travellerBands": age_counts,
            "base_usd": float(base_usd),
            "product_multiplier": float(product_multiplier),
            "usd_to_ugx": float(usd_to_ugx),
            "normalized": {
                "firstName": first_name,
                "middleName": middle_name,
                "surname": surname,
                "mobile": mobile_compact,
                "email": email,
            },
        },
    }
