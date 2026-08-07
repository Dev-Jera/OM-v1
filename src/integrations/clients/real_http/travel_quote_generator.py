"""Travel Insurance quote document generator via external Zoho endpoint."""

from __future__ import annotations

from typing import Any, Dict


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def generate_travel_quote(session_data: Dict[str, Any]) -> Dict[str, str]:
    """Generate travel benefits summary + preview URL from external Zoho endpoint."""
    quote_id = str(session_data.get("quoteid") or session_data.get("quote_id") or "").strip()
    price_incl_tax = _to_float(session_data.get("priceInclTax") or session_data.get("price_incl_tax") or 0)
    client_name = str(session_data.get("clientName") or session_data.get("fullname") or session_data.get("full_name") or "").strip()

    country_code = str(session_data.get("country") or "ug").strip().lower() or "ug"
    currency = str(session_data.get("currency") or "USD").strip().upper() or "USD"

    plan_name = str(session_data.get("planName") or session_data.get("plan_name") or "").strip()
    duration_days = _to_int(session_data.get("durationDays") or session_data.get("duration_days") or 0)
    start_date = str(session_data.get("formattedStartDate") or session_data.get("start_date") or "").strip()
    end_date = str(session_data.get("formattedEndDate") or session_data.get("end_date") or "").strip()
    destination_area = str(
        session_data.get("destinationArea")
        or session_data.get("destination_area")
        or session_data.get("destination_country")
        or ""
    ).strip()

    adults = _to_int(session_data.get("adults") or 0)
    children = _to_int(session_data.get("children") or 0)
    seniors = _to_int(session_data.get("seniors") or 0)

    if not quote_id:
        raise ValueError("quoteid is required for real travel quote integration")
    if price_incl_tax <= 0:
        raise ValueError("priceInclTax must be a positive number for real travel quote integration")

    import requests

    product_obj = {
        "name": plan_name,
        "quote_id": quote_id,
        "duration": duration_days,
        "_start_date": start_date,
        "_end_date": end_date,
        "travel": {
            "destination_area": destination_area,
            "travelers": {
                "types": {
                    "adult": adults,
                    "children": children,
                    "senior": seniors,
                }
            },
        },
        "prices": {
            "price_after_discount_incl_tax": price_incl_tax,
        },
    }

    payload = {
        "fullname": client_name,
        "context": {
            "country": country_code,
            "currency": currency,
        },
        "products": [product_obj],
    }

    url = "https://bot.uapoldmutual.com/whatsapp/qa/ug/zoho/travelInsurance/getTravelQuoteDocWithBankDetails"
    headers = {"Content-Type": "application/json"}
    api_response = requests.post(url, json=payload, headers=headers, timeout=10)
    api_response.raise_for_status()
    resp_json = api_response.json()

    if not resp_json.get("success"):
        raise RuntimeError(f"Travel quote API returned unsuccessful response: {resp_json}")

    benefits = str(resp_json.get("benefitsSummary") or "")
    benefits_url = str(resp_json.get("previewUrl") or "")

    return {
        "benefits": benefits,
        "benefitsUrl": benefits_url,
    }
