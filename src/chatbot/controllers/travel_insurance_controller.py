"""Controller for Travel Insurance flow persistence."""
from typing import Any, Dict, Optional
import logging
import re

from src.chatbot.validation import (
    raise_if_errors,
    require_str,
    optional_str,
    parse_int,
    validate_date_iso,
    validate_email,
    validate_in,
    validate_phone_ug,
    parse_iso_date,
)
from src.chatbot.travel_insurance_countries import DESTINATION_COUNTRIES, DEPARTURE_COUNTRY

logger = logging.getLogger(__name__)


class TravelInsuranceController:
    def __init__(self, db):
        self.db = db

    def create_application(self, user_id: str, initial_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        app = self.db.create_travel_application(user_id, initial_data or {})
        return self._to_dict(app)

    def get_application(self, app_id: str) -> Optional[Dict[str, Any]]:
        app = self.db.get_travel_application(app_id)
        return self._to_dict(app) if app else None

    def list_applications(
        self,
        user_id: Optional[str] = None,
        order_by: str = "created_at",
        descending: bool = True,
    ):
        apps = self.db.list_travel_applications(user_id=user_id, order_by=order_by, descending=descending)
        return [self._to_dict(a) for a in apps]

    def delete_application(self, app_id: str) -> bool:
        return self.db.delete_travel_application(app_id)

    # Step helpers
    def update_product_selection(self, app_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        errors: Dict[str, str] = {}
        product_id = _safe_str(payload.get("product_id") or payload.get("coverage_product") or payload.get("selected_product"))
        if not product_id:
            errors["product_id"] = "Product selection is required"
        raise_if_errors(errors)
        selected = None
        if product_id:
            # Lookup from available products is up to caller; store minimal
            selected = {"id": product_id}
        updates = {"selected_product": selected} if selected else {}
        app = self.db.update_travel_application(app_id, updates)
        return self._to_dict(app) if app else None

    def update_about_you(self, app_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        errors: Dict[str, str] = {}
        first_name = require_str(payload, "first_name", errors, label="First Name")
        middle_name = optional_str(payload, "middle_name")
        surname = require_str(payload, "surname", errors, label="Surname")
        # Phone and email are optional here; validate only if provided
        phone_raw = optional_str(payload, "phone_number")
        email_raw = optional_str(payload, "email")
        if phone_raw:
            validate_phone_ug(phone_raw, errors, field="phone_number")
        if email_raw:
            validate_email(email_raw, errors, field="email")
        raise_if_errors(errors)
        updates = {"about_you": {
            "first_name": first_name,
            "middle_name": middle_name,
            "surname": surname,
            "phone_number": phone_raw,
            "email": email_raw,
        }}
        app = self.db.update_travel_application(app_id, updates)
        return self._to_dict(app) if app else None

    def update_travel_party_and_trip(self, app_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        errors: Dict[str, str] = {}
        travel_party = validate_in(payload.get("travel_party", ""), {"myself_only", "myself_and_someone_else", "group"}, errors, "travel_party", required=True)
        num_18_69 = parse_int(payload, "num_travellers_18_69", errors, min_value=0, required=True)
        num_0_17 = parse_int(payload, "num_travellers_0_17", errors, min_value=0)
        num_70_75 = parse_int(payload, "num_travellers_70_75", errors, min_value=0)
        num_76_80 = parse_int(payload, "num_travellers_76_80", errors, min_value=0)
        num_81_85 = parse_int(payload, "num_travellers_81_85", errors, min_value=0)
        departure_country = validate_in(payload.get("departure_country", ""), (DEPARTURE_COUNTRY,), errors, "departure_country", required=True)
        destination_country = validate_in(payload.get("destination_country", ""), DESTINATION_COUNTRIES, errors, "destination_country", required=True)
        departure_date = validate_date_iso(payload.get("departure_date", ""), errors, "departure_date", required=True)
        return_date = validate_date_iso(payload.get("return_date", ""), errors, "return_date", required=True)
        # Date ordering check (only if both parsed)
        d1 = parse_iso_date(departure_date)
        d2 = parse_iso_date(return_date)
        if d1 and d2 and d2 < d1:
            errors["return_date"] = "Return date cannot be before departure date"
        raise_if_errors(errors)
        updates = {"travel_party_and_trip": {
            "travel_party": travel_party,
            "num_travellers_18_69": num_18_69,
            "num_travellers_0_17": num_0_17,
            "num_travellers_70_75": num_70_75,
            "num_travellers_76_80": num_76_80,
            "num_travellers_81_85": num_81_85,
            "departure_country": departure_country,
            "destination_country": destination_country,
            "departure_date": departure_date,
            "return_date": return_date,
        }}
        app = self.db.update_travel_application(app_id, updates)
        return self._to_dict(app) if app else None

    def update_data_consent(self, app_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        terms = payload.get("terms_and_conditions_agreed")
        terms_agreed: Optional[bool]
        if terms is None or terms == "":
            terms_agreed = None
        else:
            terms_agreed = terms in (True, "yes", "true", "1")

        updates = {"data_consent": {
            "terms_and_conditions_agreed": terms_agreed,
            "consent_data_outside_uganda": payload.get("consent_data_outside_uganda") in (True, "yes", "true", "1"),
            "consent_child_data": payload.get("consent_child_data") in (True, "yes", "true", "1"),
            "consent_marketing": payload.get("consent_marketing") in (True, "yes", "true", "1"),
        }}
        app = self.db.update_travel_application(app_id, updates)
        return self._to_dict(app) if app else None

    def update_traveller_details(self, app_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        errors: Dict[str, str] = {}
        first_name = require_str(payload, "first_name", errors, label="First Name")
        middle_name = optional_str(payload, "middle_name")
        surname = require_str(payload, "surname", errors, label="Surname")
        # Optional fields: validate only when provided
        nationality_type = optional_str(payload, "nationality_type")
        passport_number = optional_str(payload, "passport_number")
        dob_raw = optional_str(payload, "date_of_birth")
        if dob_raw:
            validate_date_iso(dob_raw, errors, "date_of_birth", required=True, not_future=True)
        occupation = optional_str(payload, "occupation")
        phone_raw = optional_str(payload, "phone_number")
        if phone_raw:
            validate_phone_ug(phone_raw, errors, field="phone_number")
        email_raw = optional_str(payload, "email")
        if email_raw:
            validate_email(email_raw, errors, field="email")
        postal_address = optional_str(payload, "postal_address")
        town_city = optional_str(payload, "town_city")
        office_number = optional_str(payload, "office_number")
        raise_if_errors(errors)
        app = self.db.get_travel_application(app_id)
        travellers = app.travellers if app and app.travellers else []
        primary = {
            "first_name": first_name,
            "middle_name": middle_name,
            "surname": surname,
            "nationality_type": nationality_type,
            "passport_number": passport_number,
            "date_of_birth": dob_raw,
            "occupation": occupation,
            "phone_number": phone_raw,
            "office_number": office_number,
            "email": email_raw,
            "postal_address": postal_address,
            "town_city": town_city,
        }
        if not travellers:
            travellers.append(primary)
        else:
            travellers[0] = primary
        updates = {"travellers": travellers}
        app = self.db.update_travel_application(app_id, updates)
        return self._to_dict(app) if app else None

    def update_emergency_contact(self, app_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        errors: Dict[str, str] = {}
        surname = require_str(payload, "ec_surname", errors, label="Surname")
        relationship = require_str(payload, "ec_relationship", errors, label="Relationship")
        phone_number = validate_phone_ug(payload.get("ec_phone_number", ""), errors, field="ec_phone_number")
        email_raw = require_str(payload, "ec_email", errors, label="Email")
        validate_email(email_raw, errors, field="ec_email")
        home_address = optional_str(payload, "ec_home_address")
        raise_if_errors(errors)
        updates = {"emergency_contact": {
            "surname": surname,
            "relationship": relationship,
            "phone_number": phone_number,
            "email": email_raw,
            "home_address": home_address,
        }}
        app = self.db.update_travel_application(app_id, updates)
        return self._to_dict(app) if app else None

    def update_bank_details(self, app_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        errors: Dict[str, str] = {}
        bank_name_raw = optional_str(payload, "bank_name")
        account_holder_name_raw = optional_str(payload, "account_holder_name")
        account_number_raw = optional_str(payload, "account_number")
        bank_branch_raw = optional_str(payload, "bank_branch")
        account_currency_raw = optional_str(payload, "account_currency")

        any_provided = any([bank_name_raw, account_holder_name_raw, account_number_raw, bank_branch_raw, account_currency_raw])
        if any_provided:
            bank_name = require_str(payload, "bank_name", errors, label="Bank Name")
            account_holder_name = require_str(payload, "account_holder_name", errors, label="Account Holder Name")
            account_number = require_str(payload, "account_number", errors, label="Account Number")
            bank_branch = require_str(payload, "bank_branch", errors, label="Bank Branch")
            account_currency = require_str(payload, "account_currency", errors, label="Account Currency")
            if account_number and not re.sub(r"\s", "", account_number).isdigit():
                errors["account_number"] = "Account number must be numeric"
            raise_if_errors(errors)
        else:
            bank_name = bank_name_raw
            account_holder_name = account_holder_name_raw
            account_number = account_number_raw
            bank_branch = bank_branch_raw
            account_currency = account_currency_raw
        updates = {"bank_details": {
            "bank_name": bank_name,
            "account_holder_name": account_holder_name,
            "account_number": account_number,
            "bank_branch": bank_branch,
            "account_currency": account_currency,
        }}
        app = self.db.update_travel_application(app_id, updates)
        return self._to_dict(app) if app else None

    def update_passport_upload(self, app_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        errors: Dict[str, str] = {}
        file_ref = _safe_str(payload.get("passport_file_ref"))
        if not file_ref:
            errors["passport_file_ref"] = "Passport file is required"
        raise_if_errors(errors)
        updates = {"passport_upload": {"file_ref": payload.get("passport_file_ref", "")}}
        app = self.db.update_travel_application(app_id, updates)
        return self._to_dict(app) if app else None

    def finalize_and_create_quote(self, app_id: str, user_id: str, pricing: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        app = self.db.get_travel_application(app_id)
        if not app:
            return None
        quote = self.db.create_quote(
            user_id=user_id,
            product_id=(app.selected_product or {}).get("id", "travel_insurance"),
            premium_amount=pricing.get("total_ugx"),
            sum_assured=None,
            underwriting_data={
                "selected_product": app.selected_product,
                "about_you": app.about_you,
                "travel_party_and_trip": app.travel_party_and_trip,
                "travellers": app.travellers,
                "emergency_contact": app.emergency_contact,
            },
            pricing_breakdown=pricing.get("breakdown"),
            product_name=(app.selected_product or {}).get("label", "Travel Insurance"),
        )
        updates = {"quote_id": str(quote.id), "status": "quoted"}
        self.db.update_travel_application(app_id, updates)
        app = self.db.get_travel_application(app_id)
        return self._to_dict(app) if app else None

    def _to_dict(self, app):
        if not app:
            return None
        return {
            "id": app.id,
            "user_id": app.user_id,
            "status": app.status,
            "selected_product": app.selected_product,
            "about_you": app.about_you,
            "travel_party_and_trip": app.travel_party_and_trip,
            "data_consent": app.data_consent,
            "travellers": app.travellers,
            "emergency_contact": app.emergency_contact,
            "bank_details": app.bank_details,
            "passport_upload": app.passport_upload,
            "quote_id": app.quote_id,
            "created_at": app.created_at.isoformat(),
            "updated_at": app.updated_at.isoformat(),
        }


def _safe_str(v: Any) -> str:
    return ("" if v is None else str(v)).strip()
