from __future__ import annotations

from datetime import date
from typing import Any, Dict
from uuid import uuid4

from src.integrations.clients.mocks.product_logic.travel_insurance_service import (
    build_travel_insurance_premium,
    build_travel_insurance_quote,
    build_travel_insurance_underwriting,
)


class TravelInsuranceJourneyEngine:
    product_id = "travel_insurance"

    def assess_underwriting(self, *, user_id: str, underwriting_data: Dict[str, Any], currency: str = "UGX") -> Dict[str, Any]:
        return build_travel_insurance_underwriting(
            {**underwriting_data, "user_id": user_id, "currency": currency},
            f"UW-TR-{uuid4().hex[:10].upper()}",
        )

    def calculate_premium(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict):
            data = {}

        normalized = {
            "first_name": data.get("first_name") or data.get("firstName") or "John",
            "middle_name": data.get("middle_name") or data.get("middleName") or "",
            "surname": data.get("surname") or data.get("last_name") or "Doe",
            "mobile": data.get("mobile") or data.get("phone_number") or "0700000000",
            "email": data.get("email") or "customer@example.com",
            "cover_level": (
                (data.get("selected_product") or {}).get("id") if isinstance(data.get("selected_product"), dict)
                else data.get("cover_level")
            ) or data.get("product_id") or "worldwide_essential",
            "who_are_you_covering": data.get("travel_party") or data.get("who_are_you_covering") or "myself",
            "destination_country": data.get("destination_country") or data.get("destinationCountries") or "Kenya",
            "travel_start_date": data.get("departure_date") or data.get("travel_start_date") or (date.fromordinal(date.today().toordinal() + 1).isoformat()),
            "travel_end_date": data.get("return_date") or data.get("travel_end_date") or (date.fromordinal(date.today().toordinal() + 5).isoformat()),
            "travellers": data.get("travellers") or [{"dob": data.get("dob") or "1990-01-01"}],
        }

        mock_payload = {
            "data": {
                "firstName": normalized["first_name"],
                "middleName": normalized["middle_name"],
                "surname": normalized["surname"],
                "mobile": normalized["mobile"],
                "email": normalized["email"],
                "coverLevel": normalized["cover_level"],
                "whoAreYouCovering": normalized["who_are_you_covering"],
                "destinationCountries": normalized["destination_country"],
                "travelStartDate": normalized["travel_start_date"],
                "travelEndDate": normalized["travel_end_date"],
                "travellers": normalized["travellers"],
            }
        }
        return build_travel_insurance_premium(mock_payload)

    def generate_quotation(self, *, underwriting: Dict[str, Any], currency: str = "UGX") -> Dict[str, Any]:
        return build_travel_insurance_quote(underwriting.get("raw") or underwriting, underwriting)
