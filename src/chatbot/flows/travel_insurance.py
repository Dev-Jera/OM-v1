"""
Travel Insurance flow - Customer buying journey for Old Mutual Travel products.

Flow: About you → Product selection → Travel party & trip details → Data consent →
Traveller details → Emergency contact → Passport upload →
Premium calculation → Payment.
"""


from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from src.chatbot.travel_insurance_countries import DEPARTURE_COUNTRY, DESTINATION_COUNTRIES
from src.chatbot.validation import (
    add_error,
    parse_int,
    parse_iso_date,
    raise_if_errors,
    require_str,
    validate_date_iso,
    validate_email,
    validate_in,
    validate_phone_ug,
)
from src.chatbot.flows.field_filter import filter_missing_fields
from src.chatbot.field_validator import FieldDecorator, filter_collected_fields
from src.integrations.clients.mocks.product_logic.travel_insurance_service import TravelInsurancePremiumService
from src.integrations.clients.real_http import travel_quote_generator
from src.integrations.quote_generation import generate_and_register_quote_pdf


premium_service = TravelInsurancePremiumService()

# Travel insurance product cards (from product selection screen)
TRAVEL_INSURANCE_PRODUCTS: List[Dict[str, str]] = [
    {
        "id": "worldwide_essential",
        "label": "Worldwide Essential",
        "description": "Simple insurance for worry-free international travel",
    },
    {
        "id": "worldwide_elite",
        "label": "Worldwide Elite",
        "description": "Comprehensive cover for confident world travel",
    },
    {
        "id": "schengen_essential",
        "label": "Schengen Essential",
        "description": "Core cover for travel to the Schengen-area",
    },
    {
        "id": "schengen_elite",
        "label": "Schengen Elite",
        "description": "Enhanced benefits for travel to the Schengen-area",
    },
    {
        "id": "student_cover",
        "label": "Student Cover",
        "description": "Flexible travel cover designed for students abroad",
    },
    {
        "id": "africa_asia",
        "label": "Africa & Asia",
        "description": "Tailored protection for trips across Africa and Asia",
    },
    {
        "id": "inbound_karibu",
        "label": "Inbound Karibu",
        "description": "Travel insurance for visitors coming to Uganda",
    },
]

# Sample benefits for premium summary (Worldwide Essential tier)
TRAVEL_INSURANCE_BENEFITS: List[Dict[str, str]] = [
    {
        "benefit": "Emergency medical expenses (Including epidemics and pandemics)",
        "amount": "Up to $40,000",
    },
    {
        "benefit": "Compulsory quarantine expenses (epidemics/pandemics)",
        "amount": "$85 per night up to 14 nights",
    },
    {"benefit": "Emergency medical evacuation and repatriation", "amount": "Actual Expenses"},
    {"benefit": "Emergency dental care", "amount": "Up to $250"},
    {"benefit": "Optical expenses", "amount": "Up to $100"},
    {"benefit": "Baggage delay", "amount": "$50 per hour up to $250"},
    {"benefit": "Replacement of passport and driving license", "amount": "Up to $300"},
    {"benefit": "Personal Liability", "amount": "Up to $100,000"},
]

# Relationship options for emergency contact
EMERGENCY_CONTACT_RELATIONSHIPS: Tuple[str, ...] = (
    "Spouse",
    "Parent",
    "Child",
    "Sibling",
    "Sister-in-law",
    "Brother-in-law",
    "Friend",
    "Other",
)


class TravelInsuranceFlow:
    """
    Guided flow for Travel Insurance: about you, product selection, travel details,
    data consent, traveller details, emergency contact, passport upload,
    premium calculation, then payment.
    """

    STEPS = [
        "about_you",           # 0
        "product_selection",   # 1
        "travel_party_and_trip",  # 2
        "data_consent",        # 3
        "traveller_details",   # 4
        "emergency_contact",   # 5
        "upload_passport",     # 6
        "premium_summary",     # 7
        "choose_plan_and_pay",  # 8
    ]

    def __init__(self, product_catalog: Any, db: Any) -> None:
        self.catalog = product_catalog
        self.db = db
        self.controller = None

        # Controller for persistence (optional)
        try:
            from src.chatbot.controllers.travel_insurance_controller import (  # noqa: WPS433
                TravelInsuranceController,
            )

            self.controller = TravelInsuranceController(db)
        except (ImportError, ModuleNotFoundError):
            self.controller = None

    async def start(self, user_id: str, initial_data: Dict[str, Any]) -> Dict[str, Any]:
        """Start Travel Insurance flow."""
        data: Dict[str, Any] = dict(initial_data or {})
        data.setdefault("user_id", user_id)
        data.setdefault("product_id", "travel_insurance")

        # Create persistent application record if controller available
        if self.controller:
            app = self.controller.create_application(user_id, data)
            data["application_id"] = (app or {}).get("id")

        return await self.process_step("", 0, data, user_id)

    async def process_step(
        self,
        user_input: Any,
        current_step: int,
        collected_data: Dict[str, Any],
        user_id: str,
    ) -> Dict[str, Any]:
        """Process one step of the flow."""
        payload = self._normalize_payload(user_input)

        step_handlers = [
            self._step_about_you,           # 0
            self._step_product_selection,   # 1
            self._step_travel_party_and_trip,  # 2
            self._step_data_consent,        # 3
            self._step_traveller_details,   # 4
            self._step_emergency_contact,   # 5
            self._step_upload_passport,     # 6
            self._step_premium_summary,     # 7
            self._step_choose_plan_and_pay,  # 8
        ]

        if 0 <= current_step < len(step_handlers):
            return await step_handlers[current_step](payload, collected_data, user_id)

        return {"error": "Invalid step"}

    @staticmethod
    def _normalize_payload(user_input: Any) -> Dict[str, Any]:
        """
        Normalize incoming step input into a dictionary payload.

        - None/empty -> {}
        - dict -> shallow copy
        - JSON string -> parsed dict (if valid JSON object)
        - other string -> {"_raw": "..."}
        - anything else -> {"_raw": str(...)}
        """
        if user_input is None:
            return {}

        if isinstance(user_input, dict):
            return dict(user_input)

        if isinstance(user_input, str):
            cleaned = user_input.strip()
            if not cleaned:
                return {}

            if cleaned.startswith("{") and cleaned.endswith("}"):
                try:
                    parsed = json.loads(cleaned)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    pass

            return {"_raw": cleaned}

        return {"_raw": str(user_input)}

    # ------------------------------------------------------------------ #
    # Step 0 – About You                                                   #
    # ------------------------------------------------------------------ #
    async def _step_about_you(
        self,
        payload: Dict[str, Any],
        data: Dict[str, Any],
        user_id: str,
    ) -> Dict[str, Any]:
        errors: Dict[str, str] = {}

        if payload and "_raw" not in payload:
            require_str(payload, "first_name", errors, label="First Name")
            require_str(payload, "surname", errors, label="Surname")
            validate_phone_ug(payload.get("phone_number", ""), errors, field="phone_number")
            validate_email(payload.get("email", ""), errors, field="email")

            if not errors:
                data["about_you"] = {
                    "first_name": payload.get("first_name", ""),
                    "middle_name": payload.get("middle_name", ""),
                    "surname": payload.get("surname", ""),
                    "phone_number": payload.get("phone_number", ""),
                    "email": payload.get("email", ""),
                }

                app_id = data.get("application_id")
                if self.controller and app_id:
                    self.controller.update_about_you(app_id, payload)

                # ✅ FIX: advance to product_selection (step 1), not travel details
                return await self._step_product_selection({}, data, user_id)

            raise_if_errors(errors)

        # Pre-fill from existing data
        prefilled = data.get("about_you", {})

        all_fields = [
            {
                "name": "first_name",
                "label": "First Name",
                "type": "text",
                "required": True,
                "defaultValue": prefilled.get("first_name", ""),
            },
            {
                "name": "middle_name",
                "label": "Middle Name (Optional)",
                "type": "text",
                "required": False,
                "defaultValue": prefilled.get("middle_name", ""),
            },
            {
                "name": "surname",
                "label": "Surname",
                "type": "text",
                "required": True,
                "defaultValue": prefilled.get("surname", ""),
            },
            {
                "name": "phone_number",
                "label": "Phone Number",
                "type": "tel",
                "required": True,
                "placeholder": "07XXXXXXXX",
                "defaultValue": prefilled.get("phone_number", ""),
            },
            {
                "name": "email",
                "label": "Email",
                "type": "email",
                "required": True,
                "defaultValue": prefilled.get("email", ""),
            },
        ]

        filtered_fields = filter_missing_fields(
            all_fields=all_fields,
            payload=payload,
            collected_data=data,
            validation_errors=errors,
            data_key="about_you",
        )

        fields_with_validation = FieldDecorator.decorate(filtered_fields, errors=errors)

        return {
            "response": {
                "type": "form",
                "message": (
                    "👤 About you – Get your travel insurance quote in minutes"
                    + (" - Please fix the errors below" if errors else "")
                ),
                "fields": fields_with_validation,
            },
            "next_step": 0,
            "collected_data": data,
        }

    # ------------------------------------------------------------------ #
    # Step 1 – Product Selection                                           #
    # ------------------------------------------------------------------ #
    async def _step_product_selection(self, payload: Dict, data: Dict, user_id: str) -> Dict:
        if payload and "_raw" not in payload:
            errors: Dict[str, str] = {}
            product_id = (payload.get("product_id") or payload.get("coverage_product") or "").strip()

            if product_id:
                product = next(
                    (p for p in TRAVEL_INSURANCE_PRODUCTS if p["id"] == product_id),
                    None,
                )
                if not product:
                    add_error(errors, "product_id", "Invalid product selection")
                else:
                    data["selected_product"] = product

                    app_id = data.get("application_id")
                    if self.controller and app_id:
                        self.controller.update_product_selection(app_id, {"product_id": product_id})

                raise_if_errors(errors)

                # ✅ FIX: advance to travel_party_and_trip (step 2) after a valid selection
                return await self._step_travel_party_and_trip({}, data, user_id)

        # Default selection shown on first render (no auto-advance)
        if not data.get("selected_product"):
            data["selected_product"] = TRAVEL_INSURANCE_PRODUCTS[0]

        return {
            "response": {
                "type": "product_cards",
                "message": "✈️ Select your travel insurance cover",
                "products": [
                    {
                        "id": p["id"],
                        "label": p.get("label", p.get("id", "")),
                        "description": p["description"],
                        "action": "select_cover",
                        "selected": p["id"] == data.get("selected_product", {}).get("id"),
                    }
                    for p in TRAVEL_INSURANCE_PRODUCTS
                ],
            },
            "next_step": 1,
            "collected_data": data,
        }

    # ------------------------------------------------------------------ #
    # Step 2 – Travel Party & Trip Details                                 #
    # ------------------------------------------------------------------ #
    async def _step_travel_party_and_trip(
        self,
        payload: Dict[str, Any],
        data: Dict[str, Any],
        user_id: str,
    ) -> Dict[str, Any]:
        existing_trip = data.get("travel_party_and_trip") or {}
        selected_party = str(
            payload.get("travel_party") or existing_trip.get("travel_party") or "myself_only"
        ).strip()

        travel_fields = {
            "travel_party",
            "total_travellers",
            "traveller_1_date_of_birth",
            "traveller_2_date_of_birth",
            "departure_country",
            "destination_country",
            "departure_date",
            "return_date",
        }
        has_dynamic_dob_fields = any(
            key.startswith("traveller_") and key.endswith("_date_of_birth")
            for key in payload
        )
        has_travel_submission = any(field in payload for field in travel_fields) or has_dynamic_dob_fields

        # Progressive render: only travel_party submitted → re-render form for relevant DOB/count fields
        if payload and "_raw" not in payload:
            payload_keys = set(payload.keys())
            if payload_keys == {"travel_party"}:
                existing_trip["travel_party"] = selected_party
                data["travel_party_and_trip"] = existing_trip
                return {
                    "response": {
                        "type": "form",
                        "message": "✈️ Travel details",
                        "fields": self._travel_party_fields(selected_party, existing_trip),
                        "info": "A change in number of travellers will result in a premium adjustment.",
                    },
                    "next_step": 2,
                    "collected_data": data,
                }

            if selected_party == "group" and payload_keys in ({"total_travellers"}, {"travel_party", "total_travellers"}):
                existing_trip["travel_party"] = selected_party
                total_input = self._to_non_negative_int(payload.get("total_travellers"))
                if total_input > 0:
                    existing_trip["total_travellers"] = total_input
                data["travel_party_and_trip"] = existing_trip
                return {
                    "response": {
                        "type": "form",
                        "message": "✈️ Travel details",
                        "fields": self._travel_party_fields(selected_party, existing_trip),
                        "info": "A change in number of travellers will result in a premium adjustment.",
                    },
                    "next_step": 2,
                    "collected_data": data,
                }

        if payload and "_raw" not in payload and has_travel_submission:
            errors: Dict[str, str] = {}

            travel_party = validate_in(
                payload.get("travel_party", existing_trip.get("travel_party", "")),
                ("myself_only", "myself_and_someone_else", "group"),
                errors,
                "travel_party",
                required=True,
            )

            n18_69 = 0
            n0_17 = 0
            n70_75 = 0
            n76_80 = 0
            n81_85 = 0
            total_travellers = 0
            traveller_date_of_births: List[str] = []

            if travel_party in ("myself_only", "myself_and_someone_else"):
                total_travellers = 1 if travel_party == "myself_only" else 2

            elif travel_party == "group":
                total_travellers = parse_int(payload, "total_travellers", errors, min_value=1, required=True)

            if travel_party in ("myself_only", "myself_and_someone_else", "group") and total_travellers > 0:
                for index in range(1, total_travellers + 1):
                    field_name = f"traveller_{index}_date_of_birth"
                    dob_value = validate_date_iso(
                        payload.get(field_name, ""),
                        errors,
                        field_name,
                        required=True,
                        not_future=True,
                    )

                    if not dob_value:
                        continue

                    traveller_date_of_births.append(dob_value)

                    parsed_dob = parse_iso_date(dob_value)
                    if not parsed_dob:
                        continue

                    age = self._calculate_age(parsed_dob)
                    if index == 1 and age < 18:
                        add_error(errors, field_name, "Person applying must be at least 18 years old")
                        continue
                    if age > 85:
                        add_error(errors, field_name, "Traveller age must be 85 years or below")
                        continue

                    bucket = self._age_bucket(age)
                    if bucket == "0_17":
                        n0_17 += 1
                    elif bucket == "18_69":
                        n18_69 += 1
                    elif bucket == "70_75":
                        n70_75 += 1
                    elif bucket == "76_80":
                        n76_80 += 1
                    elif bucket == "81_85":
                        n81_85 += 1

            departure_country = validate_in(
                payload.get("departure_country", DEPARTURE_COUNTRY),
                (DEPARTURE_COUNTRY,),
                errors,
                "departure_country",
                required=True,
            )
            destination_country = validate_in(
                payload.get("destination_country", ""),
                DESTINATION_COUNTRIES,
                errors,
                "destination_country",
                required=True,
            )

            departure_date = validate_date_iso(payload.get("departure_date", ""), errors, "departure_date", required=True)
            return_date = validate_date_iso(payload.get("return_date", ""), errors, "return_date", required=True)

            dd = parse_iso_date(departure_date)
            rd = parse_iso_date(return_date)
            if dd and rd and rd < dd:
                add_error(errors, "return_date", "Return date must be on or after the departure date")

            raise_if_errors(errors)

            data["travel_party_and_trip"] = {
                "travel_party": travel_party,
                "total_travellers": total_travellers,
                "traveller_1_date_of_birth": traveller_date_of_births[0] if len(traveller_date_of_births) >= 1 else "",
                "traveller_2_date_of_birth": traveller_date_of_births[1] if len(traveller_date_of_births) >= 2 else "",
                "traveller_date_of_births": traveller_date_of_births,
                "num_travellers_18_69": n18_69,
                "num_travellers_0_17": n0_17,
                "num_travellers_70_75": n70_75,
                "num_travellers_76_80": n76_80,
                "num_travellers_81_85": n81_85,
                "departure_country": departure_country,
                "destination_country": destination_country,
                "departure_date": departure_date,
                "return_date": return_date,
            }

            app_id = data.get("application_id")
            if self.controller and app_id:
                self.controller.update_travel_party_and_trip(app_id, payload)

            # ✅ FIX: advance to data_consent (step 3) on successful submission
            return await self._step_data_consent({}, data, user_id)

        return {
            "response": {
                "type": "form",
                "message": "✈️ Travel details",
                "fields": self._travel_party_fields(selected_party, existing_trip),
                "info": "A change in number of travellers will result in a premium adjustment.",
            },
            "next_step": 2,
            "collected_data": data,
        }

    def _travel_party_fields(self, selected_party: str, trip_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        fields: List[Dict[str, Any]] = [
            {
                "name": "travel_party",
                "label": "Travel party",
                "type": "radio",
                "defaultValue": selected_party,
                "options": [
                    {"id": "myself_only", "value": "myself_only", "label": "Myself only"},
                    {"id": "myself_and_someone_else", "value": "myself_and_someone_else", "label": "Myself and someone else"},
                    {"id": "group", "value": "group", "label": "Group"},
                ],
                "required": True,
            }
        ]

        if selected_party in ("myself_only", "myself_and_someone_else"):
            fields.append({
                "name": "traveller_1_date_of_birth",
                "label": "Your Date of Birth",
                "type": "date",
                "required": True,
                "defaultValue": trip_data.get("traveller_1_date_of_birth", ""),
            })

        if selected_party == "myself_and_someone_else":
            fields.append({
                "name": "traveller_2_date_of_birth",
                "label": "Second Traveller Date of Birth",
                "type": "date",
                "required": True,
                "defaultValue": trip_data.get("traveller_2_date_of_birth", ""),
            })

        if selected_party == "group":
            total_group_travellers = self._to_non_negative_int(trip_data.get("total_travellers"))
            group_dob_prefills = trip_data.get("traveller_date_of_births") or []
            fields.append(
                {
                    "name": "total_travellers",
                    "label": "Total number of travellers",
                    "type": "number",
                    "min": 1,
                    "required": True,
                    "defaultValue": trip_data.get("total_travellers", ""),
                }
            )
            for index in range(1, total_group_travellers + 1):
                fields.append(
                    {
                        "name": f"traveller_{index}_date_of_birth",
                        "label": f"Traveller {index} Date of Birth",
                        "type": "date",
                        "required": True,
                        "defaultValue": group_dob_prefills[index - 1] if index - 1 < len(group_dob_prefills) else "",
                    }
                )

        fields.extend([
            {
                "name": "departure_country",
                "label": "Departure Country",
                "type": "select",
                "defaultValue": trip_data.get("departure_country", DEPARTURE_COUNTRY),
                "options": [{"value": DEPARTURE_COUNTRY, "label": DEPARTURE_COUNTRY}],
                "required": True,
            },
            {
                "name": "destination_country",
                "label": "Destination Country",
                "type": "select",
                "defaultValue": trip_data.get("destination_country", ""),
                "options": [{"value": country, "label": country} for country in DESTINATION_COUNTRIES],
                "required": True,
            },
            {"name": "departure_date", "label": "Departure Date", "type": "date", "required": True, "defaultValue": trip_data.get("departure_date", "")},
            {"name": "return_date", "label": "Return Date", "type": "date", "required": True, "defaultValue": trip_data.get("return_date", "")},
        ])

        return FieldDecorator.decorate(fields)

    @staticmethod
    def _calculate_age(dob: date) -> int:
        today = date.today()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    @staticmethod
    def _age_bucket(age: int) -> Optional[str]:
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

    @staticmethod
    def _to_non_negative_int(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return parsed if parsed >= 0 else 0

    def _derive_total_travellers_needed(self, trip_info: Dict[str, Any]) -> int:
        explicit_total = self._to_non_negative_int(trip_info.get("total_travellers"))
        return explicit_total or 1

    # ------------------------------------------------------------------ #
    # Step 3 – Data Consent                                                #
    # ------------------------------------------------------------------ #
    async def _step_data_consent(
        self,
        payload: Dict[str, Any],
        data: Dict[str, Any],
        user_id: str,
    ) -> Dict[str, Any]:
        if payload and "_raw" not in payload:
            errors: Dict[str, str] = {}
            terms = payload.get("terms_and_conditions_agreed")
            terms_agreed: Optional[bool]
            if terms is None or terms == "":
                terms_agreed = None
            else:
                terms_agreed = terms in (True, "yes", "true", "1")

            consent_data_outside_uganda = payload.get("consent_data_outside_uganda") in (True, "yes", "true", "1")
            if not consent_data_outside_uganda:
                add_error(errors, "consent_data_outside_uganda", "You must consent to data processing outside Uganda to continue")

            raise_if_errors(errors)

            data["data_consent"] = {
                "terms_and_conditions_agreed": terms_agreed,
                "consent_data_outside_uganda": consent_data_outside_uganda,
                "consent_child_data": payload.get("consent_child_data") in (True, "yes", "true", "1"),
                "consent_marketing": payload.get("consent_marketing") in (True, "yes", "true", "1"),
            }

            app_id = data.get("application_id")
            if self.controller and app_id:
                self.controller.update_data_consent(app_id, payload)

            # ✅ FIX: advance to traveller_details (step 4) after consent is submitted
            return await self._step_traveller_details({}, data, user_id)

        return {
            "response": {
                "type": "consent",
                "message": "📋 Before we begin – Data consent",
                "consents": [
                    {
                        "id": "terms_and_conditions_agreed",
                        "label": "I have read and understand the Terms and Conditions.",
                        "required": False,
                        "link": "https://www.oldmutual.co.ug/terms",
                    },
                    {
                        "id": "consent_data_outside_uganda",
                        "label": "I consent to processing of my personal data outside Uganda (as per Privacy Notice and Privacy Policy).",
                        "required": True,
                    },
                    {
                        "id": "consent_child_data",
                        "label": "I am the parent/legal guardian and consent to processing of my child's personal data (if children are travelling).",
                        "required": False,
                    },
                    {
                        "id": "consent_marketing",
                        "label": "I consent to receive information about insurance/financial products and special offers. (You can opt-out anytime.)",
                        "required": False,
                    },
                ],
            },
            "next_step": 3,
            "collected_data": data,
        }

    # ------------------------------------------------------------------ #
    # Step 4 – Traveller Details (loops until all travellers collected)    #
    # ------------------------------------------------------------------ #
    async def _step_traveller_details(
        self,
        payload: Dict[str, Any],
        data: Dict[str, Any],
        user_id: str,
    ) -> Dict[str, Any]:
        trip_info = data.get("travel_party_and_trip") or {}
        total_needed = self._derive_total_travellers_needed(trip_info)

        if "travellers" not in data:
            data["travellers"] = []

        current_travellers = data["travellers"]
        current_index = len(current_travellers) + 1

        # Pre-fill first traveller from About You and map DOB by traveller index.
        prefill: Dict[str, Any] = {}
        if current_index == 1:
            prefill = dict(data.get("about_you") or {})

        # Determine if DOB was already collected in Step 2.
        # Keep traveller 1 pre-filled, but still show a date picker for "other traveller".
        travel_party = trip_info.get("travel_party", "")
        dob_collected_in_step2 = travel_party in ("myself_only", "myself_and_someone_else") and current_index == 1

        dob_prefills = trip_info.get("traveller_date_of_births") or []
        indexed_dob_prefill = ""
        if current_index - 1 < len(dob_prefills):
            indexed_dob_prefill = str(dob_prefills[current_index - 1] or "")
        elif current_index == 1:
            indexed_dob_prefill = str(trip_info.get("traveller_1_date_of_birth") or "")
        elif current_index == 2:
            indexed_dob_prefill = str(trip_info.get("traveller_2_date_of_birth") or "")

        traveller_prefill = {
            "first_name": prefill.get("first_name", ""),
            "middle_name": "",
            "surname": prefill.get("surname", ""),
            "nationality_type": prefill.get("nationality_type", ""),
            "passport_number": prefill.get("passport_number", ""),
            "date_of_birth": indexed_dob_prefill,
            "occupation": prefill.get("occupation", ""),
            "phone_number": prefill.get("phone_number", ""),
            "email": prefill.get("email", ""),
            "_dob_collected_in_step2": dob_collected_in_step2,
        }

        if payload and "_raw" not in payload:
            errors: Dict[str, str] = {}

            # Merge pre-filled values so hidden fields remain valid on submit.
            merged_payload = dict(traveller_prefill)
            merged_payload.update(payload)

            first_name = require_str(merged_payload, "first_name", errors, label="First Name")
            surname = require_str(merged_payload, "surname", errors, label="Surname")
            nationality_type = validate_in(
                merged_payload.get("nationality_type", ""),
                ("ugandan", "non_ugandan"),
                errors,
                "nationality_type",
                required=True,
            )
            passport_number = require_str(merged_payload, "passport_number", errors, label="Passport Number")
            if passport_number and not re.fullmatch(r"\d{10}", passport_number):
                add_error(errors, "passport_number", "Passport Number must be exactly 10 digits")

            date_of_birth = validate_date_iso(
                merged_payload.get("date_of_birth", ""),
                errors,
                "date_of_birth",
                required=True,
                not_future=True,
            )
            occupation = require_str(merged_payload, "occupation", errors, label="Profession/Occupation")
            phone_number = validate_phone_ug(merged_payload.get("phone_number", ""), errors, field="phone_number")
            email = validate_email(merged_payload.get("email", ""), errors, field="email")

            parsed_dob = parse_iso_date(date_of_birth)
            if current_index == 1 and parsed_dob and self._calculate_age(parsed_dob) < 18:
                add_error(errors, "date_of_birth", "Person applying must be at least 18 years old")

            raise_if_errors(errors)

            new_traveller = {
                "first_name": first_name,
                "middle_name": str(merged_payload.get("middle_name", "") or ""),
                "surname": surname,
                "nationality_type": nationality_type,
                "passport_number": passport_number,
                "date_of_birth": date_of_birth,
                "occupation": occupation,
                "phone_number": phone_number,
                "email": email,
            }

            data["travellers"].append(new_traveller)

            app_id = data.get("application_id")
            if self.controller and app_id:
                self.controller.update_traveller_details(app_id, data["travellers"])

            if len(data["travellers"]) < total_needed:
                # More travellers to collect — loop back
                return await self._step_traveller_details({}, data, user_id)
            else:
                # ✅ All travellers collected — advance to emergency_contact (step 5)
                return await self._step_emergency_contact({}, data, user_id)

        msg = f"👤 Traveller {current_index} of {total_needed} – Please provide details"
        if total_needed == 1:
            msg = "👤 Traveller details – Please provide your details"
        elif current_index == 2 and travel_party == "myself_and_someone_else":
            msg = "👤 Other Traveller – Please provide their details"

        all_fields = [
            {
                "name": "first_name",
                "label": "First Name",
                "type": "text",
                "required": True,
                "defaultValue": traveller_prefill.get("first_name", ""),
            },
            {
                "name": "middle_name",
                "label": "Middle Name (Optional)",
                "type": "text",
                "required": False,
                "defaultValue": traveller_prefill.get("middle_name", ""),
            },
            {
                "name": "surname",
                "label": "Surname",
                "type": "text",
                "required": True,
                "defaultValue": traveller_prefill.get("surname", ""),
            },
            {
                "name": "nationality_type",
                "label": "Nationality Type",
                "type": "radio",
                "defaultValue": traveller_prefill.get("nationality_type", ""),
                "options": [
                    {"id": "ugandan", "value": "ugandan", "label": "Ugandan"},
                    {"id": "non_ugandan", "value": "non_ugandan", "label": "Non-Ugandan"},
                ],
                "required": True,
            },
            {
                "name": "passport_number",
                "label": "Passport Number",
                "type": "text",
                "required": True,
                "defaultValue": traveller_prefill.get("passport_number", ""),
            },
        ]

        # Skip DOB if already collected in Step 2 for myself/plus-one scenarios
        if not traveller_prefill.get("_dob_collected_in_step2"):
            all_fields.append({
                "name": "date_of_birth",
                "label": "Date of Birth",
                "type": "date",
                "required": True,
                "defaultValue": traveller_prefill.get("date_of_birth", ""),
            })

        all_fields.extend([
            {
                "name": "occupation",
                "label": "Profession/Occupation",
                "type": "text",
                "required": True,
                "defaultValue": traveller_prefill.get("occupation", ""),
            },
            {
                "name": "phone_number",
                "label": "Phone Number",
                "type": "tel",
                "required": True,
                "defaultValue": traveller_prefill.get("phone_number", ""),
            },
            {
                "name": "email",
                "label": "Email",
                "type": "email",
                "required": True,
                "defaultValue": traveller_prefill.get("email", ""),
            },
        ])

        fields_to_render = all_fields
        has_data_consent = bool((data.get("data_consent") or {}).get("consent_data_outside_uganda"))
        if current_index == 1 and has_data_consent:
            fields_to_render = filter_collected_fields(
                all_fields=all_fields,
                collected_data=data,
                previous_step_keys=["about_you"],
            )
            # Do not re-ask optional fields for traveller 1 after About You.
            fields_to_render = [f for f in fields_to_render if f.get("required", False)]

        fields_with_validation = FieldDecorator.decorate(fields_to_render)

        return {
            "response": {
                "type": "form",
                "message": msg,
                "fields": fields_with_validation,
            },
            "next_step": 4,
            "collected_data": data,
        }

    # ------------------------------------------------------------------ #
    # Step 5 – Emergency Contact                                           #
    # ------------------------------------------------------------------ #
    async def _step_emergency_contact(
        self,
        payload: Dict[str, Any],
        data: Dict[str, Any],
        user_id: str,
    ) -> Dict[str, Any]:
        errors: Dict[str, str] = {}
        prefill = dict(data.get("emergency_contact") or {})

        if payload and "_raw" not in payload:
            require_str(payload, "ec_surname", errors, label="Surname")
            validate_in(payload.get("ec_relationship", ""), EMERGENCY_CONTACT_RELATIONSHIPS, errors, "ec_relationship", required=True)
            require_str(payload, "ec_phone_number", errors, label="Phone Number")
            validate_phone_ug(payload.get("ec_phone_number", ""), errors, field="ec_phone_number")
            require_str(payload, "ec_email", errors, label="Email Address")
            validate_email(payload.get("ec_email", ""), errors, field="ec_email")

            prefill.update(
                {
                    "ec_surname": payload.get("ec_surname", ""),
                    "ec_relationship": payload.get("ec_relationship", ""),
                    "ec_phone_number": payload.get("ec_phone_number", ""),
                    "ec_email": payload.get("ec_email", ""),
                    "ec_home_address": payload.get("ec_home_address", ""),
                }
            )

            if not errors:
                data["emergency_contact"] = {
                    "surname": payload.get("ec_surname", ""),
                    "relationship": payload.get("ec_relationship", ""),
                    "phone_number": payload.get("ec_phone_number", ""),
                    "email": payload.get("ec_email", ""),
                    "home_address": payload.get("ec_home_address", ""),
                }

                app_id = data.get("application_id")
                if self.controller and app_id:
                    self.controller.update_emergency_contact(app_id, payload)

                # ✅ FIX: advance to upload_passport (step 6)
                return await self._step_upload_passport({}, data, user_id)

            raise_if_errors(errors)

        fields = [
            {
                "name": "ec_surname",
                "label": "Surname",
                "type": "text",
                "required": True,
                "defaultValue": prefill.get("ec_surname", ""),
            },
            {
                "name": "ec_relationship",
                "label": "Relationship",
                "type": "select",
                "options": [{"value": rel, "label": rel} for rel in EMERGENCY_CONTACT_RELATIONSHIPS],
                "required": True,
                "defaultValue": prefill.get("ec_relationship", ""),
            },
            {
                "name": "ec_phone_number",
                "label": "Phone Number",
                "type": "tel",
                "required": True,
                "defaultValue": prefill.get("ec_phone_number", ""),
            },
            {
                "name": "ec_email",
                "label": "Email Address",
                "type": "email",
                "required": True,
                "defaultValue": prefill.get("ec_email", ""),
            },
            {
                "name": "ec_home_address",
                "label": "Home/Postal Address",
                "type": "text",
                "required": False,
                "defaultValue": prefill.get("ec_home_address", ""),
            },
        ]

        return {
            "response": {
                "type": "form",
                "message": (
                    "📞 Emergency contact / beneficiary"
                    + (" - Please fix the errors below" if errors else "")
                ),
                "fields": FieldDecorator.decorate(fields, errors=errors),
            },
            "next_step": 5,
            "collected_data": data,
        }

    # ------------------------------------------------------------------ #
    # Step 6 – Upload Passport                                             #
    # ------------------------------------------------------------------ #
    async def _step_upload_passport(
        self,
        payload: Dict[str, Any],
        data: Dict[str, Any],
        user_id: str,
    ) -> Dict[str, Any]:
        if payload and "_raw" not in payload:
            errors: Dict[str, str] = {}
            file_ref = require_str(payload, "passport_file_ref", errors, label="Passport file")
            raise_if_errors(errors)

            data["passport_upload"] = {"file_ref": file_ref, "uploaded_at": datetime.utcnow().isoformat()}

            app_id = data.get("application_id")
            if self.controller and app_id:
                self.controller.update_passport_upload(app_id, payload)

            # ✅ FIX: advance to premium_summary (step 7)
            return await self._step_premium_summary({}, data, user_id)

        return {
            "response": {
                "type": "file_upload",
                "message": "📄 Upload copy of Passport Bio Data Page",
                "accept": "application/pdf,image/jpeg,image/jpg",
                "field_name": "passport_file_ref",
                "max_size_mb": 1,
                "help": "PDF, JPEG or JPG. Max 1 MB",
            },
            "next_step": 6,
            "collected_data": data,
        }

    # ------------------------------------------------------------------ #
    # Step 7 – Premium Summary                                             #
    # ------------------------------------------------------------------ #
    async def _step_premium_summary(
        self,
        payload: Dict[str, Any],
        data: Dict[str, Any],
        user_id: str,
    ) -> Dict[str, Any]:
        # Handle action buttons from premium summary
        if any(token in str(payload.get("action") or payload.get("_raw") or "").strip().lower() for token in ("proceed", "pay")):
            return await self._step_choose_plan_and_pay(payload, data, user_id)

        # Allow the UI to pass the upload ref again on this step without failing
        if payload.get("passport_file_ref") and not data.get("passport_upload"):
            data["passport_upload"] = {
                "file_ref": payload.get("passport_file_ref", ""),
                "uploaded_at": datetime.utcnow().isoformat(),
            }
            app_id = data.get("application_id")
            if self.controller and app_id:
                self.controller.update_passport_upload(app_id, payload)

        trip = data.get("travel_party_and_trip") or {}
        total_premium = self._calculate_travel_premium(data)

        app_id = data.get("application_id")
        if self.controller and app_id:
            self.controller.update_travel_party_and_trip(app_id, data.get("travel_party_and_trip", {}))

        try:
            quote_result = generate_and_register_quote_pdf(
                "travel_insurance",
                data,
                product_name="Travel Insurance",
            )
            quote_id = quote_result.get("quote_id", "")
            download_url = quote_result.get("download_url", "")
            data["integration_quote_id"] = quote_id
            data["integration_download_url"] = download_url
        except Exception as e:
            # Reuse previously generated quote metadata when regeneration fails.
            quote_id = str(data.get("integration_quote_id") or "")
            download_url = str(data.get("integration_download_url") or "")
            # Store error for debugging if needed
            data["_quote_generation_error"] = str(e)

        return {
            "response": {
                "type": "premium_summary",
                "message": "💰 Premium Calculation",
                "product_name": (data.get("selected_product") or {}).get("label", "Travel Insurance"),
                "total_premium_usd": total_premium.get("total_usd", 0),
                "total_premium_ugx": total_premium.get("total_ugx", 0),
                "covering": trip.get("travel_party", "Myself"),
                "period_of_coverage": self._get_period_text(trip),
                "trip_details": {
                    "departure_country": trip.get("departure_country", ""),
                    "destination_country": trip.get("destination_country", ""),
                    "departure_date": trip.get("departure_date", ""),
                    "return_date": trip.get("return_date", ""),
                },
                "benefits": TRAVEL_INSURANCE_BENEFITS,
                "breakdown": total_premium.get("breakdown", {}),
                "quote_id": quote_id,
                "download_url": download_url,
                "download_option": bool(download_url),
                "download_label": "Download Quote",
                "actions": [
                    {"type": "download_quote", "label": "Download Quote"},
                    {"type": "proceed_to_pay", "label": "Proceed to Pay"},
                ],
            },
            "next_step": 7,
            "collected_data": data,
        }

    # ------------------------------------------------------------------ #
    # Step 8 – Choose Plan & Pay                                           #
    # ------------------------------------------------------------------ #
    async def _step_choose_plan_and_pay(
        self,
        payload: Dict[str, Any],
        data: Dict[str, Any],
        user_id: str,
    ) -> Dict[str, Any]:
        # Handle proceed to payment (explicit or fall-through from other actions)
        if not data.get("quote_id"):
            total_premium = self._calculate_travel_premium(data)
            product = data.get("selected_product") or TRAVEL_INSURANCE_PRODUCTS[0]

            app_id = data.get("application_id")
            if self.controller and app_id:
                try:
                    app = self.controller.finalize_and_create_quote(app_id, user_id, total_premium)
                    data["quote_id"] = (app or {}).get("quote_id")
                except Exception:
                    data["quote_id"] = None

            if not data.get("quote_id") and self.db:
                try:
                    quote = self.db.create_quote(
                        user_id=user_id,
                        product_id=data.get("product_id", "travel_insurance"),
                        premium_amount=total_premium["total_ugx"],
                        sum_assured=None,
                        underwriting_data=data,
                        pricing_breakdown=total_premium.get("breakdown"),
                        product_name=product.get("label", "Travel Insurance"),
                    )
                    data["quote_id"] = str(quote.id)
                except Exception:
                    data["quote_id"] = None

            if not data.get("quote_id"):
                return {
                    "response": {
                        "type": "error",
                        "message": "Failed to create quote. Please try again.",
                    },
                    "next_step": 8,
                    "collected_data": data,
                }

        total_premium = self._calculate_travel_premium(data)
        integration_download_url = str(data.get("integration_download_url") or "")
        integration_quote_id = str(data.get("integration_quote_id") or "")
        return {
            "response": {
                "type": "proceed_to_payment",
                "message": "Proceeding to payment. Choose Mobile Money (MTN/Airtel) or Bank Transfer.",
                "quote_id": str(data.get("quote_id", "")),
                "preview_quote_id": integration_quote_id,
                "download_url": integration_download_url,
                "download_option": bool(integration_download_url),
                "download_label": "Download Quote",
                "total_due_ugx": total_premium["total_ugx"],
                "payment_options": [
                    {"id": "mobile_money", "label": "Mobile Money", "providers": ["MTN", "Airtel"]},
                    {"id": "bank_transfer", "label": "Bank Transfer"},
                ],
            },
            "complete": True,
            "next_flow": "payment",
            "collected_data": data,
            "data": {"quote_id": str(data.get("quote_id", ""))},
        }

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _get_period_text(trip: Dict[str, Any]) -> str:
        dd = trip.get("departure_date")
        rd = trip.get("return_date")
        if dd and rd:
            return f"{dd} to {rd}"
        if dd:
            return f"From {dd}"
        return "Not provided"

    def _calculate_travel_premium(self, data: Dict[str, Any]) -> Dict[str, Any]:
        premium = premium_service.calculate_sync("travel_insurance", {"data": data})
        trip = data.get("travel_party_and_trip") or {}
        departure_date = parse_iso_date(str(trip.get("departure_date") or ""))
        return_date = parse_iso_date(str(trip.get("return_date") or ""))
        trip_days = 1
        if departure_date and return_date and return_date >= departure_date:
            trip_days = (return_date - departure_date).days + 1

        benefits = ""
        benefits_url = ""
        try:
            preview_meta = travel_quote_generator.generate_travel_quote(
                {
                    "departure_date": trip.get("departure_date"),
                    "return_date": trip.get("return_date"),
                    "product_id": (data.get("selected_product") or {}).get("id"),
                }
            ) or {}
            benefits = str(preview_meta.get("benefits") or "").strip()
            benefits_url = str(preview_meta.get("benefitsUrl") or "").strip()
        except Exception:
            benefits = ""
            benefits_url = ""

        premium.setdefault("breakdown", {})
        premium["breakdown"].setdefault("days", trip_days)
        premium["breakdown"].setdefault("benefits", benefits)
        premium["breakdown"].setdefault("benefitsUrl", benefits_url)
        return premium
