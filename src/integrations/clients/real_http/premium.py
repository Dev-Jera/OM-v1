"""Real premium client.

Current implementation is rule-based and mirrors existing flow logic exactly,
while preserving each product output structure.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4
from typing import Any, Dict, Optional

from src.integrations.contracts.premium import PremiumContract


class RealPremiumClient(PremiumContract):
    """Real premium client (ready for future HTTP integration)."""

    async def calculate_premium(self, product_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.calculate_premium_sync(product_key, payload)

    def calculate_premium_sync(self, product_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self._normalize_product_key(product_key)

        if normalized == "personal_accident":
            return self._calculate_personal_accident_premium(payload)
        if normalized == "serenicare":
            return self._calculate_serenicare_premium(payload)
        if normalized == "travel_insurance":
            return self._calculate_travel_premium(payload)
        if normalized == "motor_private":
            return self._calculate_motor_private_premium(payload)

        raise ValueError(f"Unsupported product_key for premium calculation: {product_key}")

    @staticmethod
    def _normalize_product_key(product_key: str) -> str:
        normalized = str(product_key or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "travel": "travel_insurance",
            "travel_insurance": "travel_insurance",
            "personal_accident": "personal_accident",
            "motor_private": "motor_private",
            "serenicare": "serenicare",
        }
        if normalized not in aliases:
            raise ValueError(f"Unsupported product_key for premium calculation: {product_key}")
        return aliases[normalized]

    @staticmethod
    def _calculate_personal_accident_premium(payload: Dict[str, Any]) -> Dict[str, Any]:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else (payload if isinstance(payload, dict) else {})
        sum_assured = int(payload.get("sum_assured") or 0)

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

    @staticmethod
    def _calculate_serenicare_premium(payload: Dict[str, Any]) -> Dict[str, Any]:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else (payload if isinstance(payload, dict) else {})
        plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}

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

    @staticmethod
    def _calculate_travel_premium(payload: Dict[str, Any]) -> Dict[str, Any]:
        from src.integrations.clients.real_http.travel_quote_generator import generate_travel_quote

        data = payload.get("data") if isinstance(payload.get("data"), dict) else (payload if isinstance(payload, dict) else {})
        trip = data.get("travel_party_and_trip") or {}
        days = RealPremiumClient._calculate_trip_days(trip.get("departure_date"), trip.get("return_date"))

        travellers_18_69 = int(trip.get("num_travellers_18_69") or 0)
        travellers_0_17 = int(trip.get("num_travellers_0_17") or 0)
        travellers_70_75 = int(trip.get("num_travellers_70_75") or 0)
        travellers_76_80 = int(trip.get("num_travellers_76_80") or 0)
        travellers_81_85 = int(trip.get("num_travellers_81_85") or 0)

        product = data.get("selected_product") or {}
        product_id = product.get("id", "worldwide_essential")

        raw_total_usd = (
            data.get("priceInclTax")
            or data.get("price_incl_tax")
            or payload.get("priceInclTax")
            or payload.get("price_incl_tax")
            or payload.get("total_usd")
        )
        if raw_total_usd in (None, ""):
            raise ValueError("Missing required field 'priceInclTax' for real travel premium integration")

        total_usd = Decimal(str(raw_total_usd)).quantize(Decimal("0.01"))
        if total_usd <= 0:
            raise ValueError("Field 'priceInclTax' must be greater than 0 for real travel premium integration")

        usd_to_ugx = Decimal("3900")
        total_ugx = (total_usd * usd_to_ugx).quantize(Decimal("1."))

        quote_id = str(data.get("quoteid") or data.get("quote_id") or payload.get("quoteid") or payload.get("quote_id") or "").strip()
        if not quote_id:
            quote_id = f"TRAVEL-{uuid4().hex[:12].upper()}"

        client_name = ""
        about_you = data.get("about_you") if isinstance(data.get("about_you"), dict) else {}
        if about_you:
            first_name = str(about_you.get("first_name") or "").strip()
            surname = str(about_you.get("surname") or "").strip()
            client_name = f"{first_name} {surname}".strip()

        external_quote = generate_travel_quote(
            {
                "quoteid": quote_id,
                "priceInclTax": float(total_usd),
                "clientName": client_name,
                "planName": str(product.get("label") or product_id),
                "durationDays": days,
                "formattedStartDate": str(trip.get("departure_date") or ""),
                "formattedEndDate": str(trip.get("return_date") or ""),
                "destinationArea": str(trip.get("destination_area") or trip.get("destination_country") or ""),
                "adults": travellers_18_69,
                "children": travellers_0_17,
                "seniors": travellers_70_75 + travellers_76_80 + travellers_81_85,
                "country": "ug",
                "currency": "USD",
            }
        )

        breakdown: Dict[str, Any] = {
            "days": days,
            "product_id": product_id,
            "travellers": {
                "18_69": travellers_18_69,
                "0_17": travellers_0_17,
                "70_75": travellers_70_75,
                "76_80": travellers_76_80,
                "81_85": travellers_81_85,
            },
            "usd_to_ugx": float(usd_to_ugx),
            "quoteid": quote_id,
            "benefits": external_quote.get("benefits", ""),
            "benefitsUrl": external_quote.get("benefitsUrl", ""),
        }

        return {
            "total_usd": float(total_usd),
            "total_ugx": float(total_ugx),
            "breakdown": breakdown,
        }

    @staticmethod
    def _calculate_motor_private_premium(payload: Dict[str, Any]) -> Dict[str, Any]:
        from src.integrations.clients.real_http.motor_private_calculator import calculate_motor_private_premium

        # Extract data dict from payload if present
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

        # Calculate premium using Zoho Deluge formula
        result = calculate_motor_private_premium(data)

        return result

    @staticmethod
    def _calculate_trip_days(departure_date: Any, return_date: Any) -> int:
        d1 = RealPremiumClient._safe_iso_date(departure_date)
        d2 = RealPremiumClient._safe_iso_date(return_date)
        if not d1 or not d2:
            return 1
        return max(1, (d2 - d1).days + 1)

    @staticmethod
    def _safe_iso_date(value: Any) -> Optional[date]:
        from datetime import datetime

        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value)).date()
        except (TypeError, ValueError):
            return None


real_premium_client = RealPremiumClient()
