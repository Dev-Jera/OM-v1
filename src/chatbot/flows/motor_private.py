"""
Motor Private flow - Collect vehicle details, deductible choices, additional benefits,
premium calculation, user details, then proceed to payment.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from datetime import date

from src.chatbot.validation import (
    raise_if_errors,
    require_str,
    parse_int,
    validate_email,
    validate_in,
    validate_phone_ug,
    validate_enum,
    validate_length_range,
    validate_uganda_mobile_frontend,
    validate_motor_email_frontend,
    validate_cover_start_date_range,
)
from src.chatbot.flows.field_filter import filter_missing_fields
from src.chatbot.field_validator import FieldDecorator
from src.integrations.clients.mocks.product_logic.motor_private import (
    build_motor_private_quotation,
    generate_motor_private_quote_pdf,
)
from src.integrations.policy.journey_orchestrator import journey_orchestrator
from src.integrations.product_benefits import product_benefits_loader
from src.integrations.quote_downloads import register_quote_pdf
from src.integrations.underwriting import run_quote_preview


class _PremiumServiceShim:
    @staticmethod
    def calculate_sync(product_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return journey_orchestrator.calculate_product_premium(product_key, payload)


premium_service = _PremiumServiceShim()

MOTOR_PRIVATE_EXCESS_PARAMETERS = [
    {
        "id": "excess_1",
        "label": "10% of claim, UGX 1,000,000 to UGX 3,000,000\n10% of total premium"
    },
    {
        "id": "excess_2",
        "label": "10% of claim, UGX 3,000,001 to UGX 4,000,000\n15% of total premium"
    },
    {
        "id": "excess_3",
        "label": "10% of claim, UGX 4,000,001 to UGX 5,000,000\n25% of total premium"
    }
]

MOTOR_PRIVATE_ADDITIONAL_BENEFITS = [
    {
        "id": "political_violence",
        "label": "Political violence and terrorism\n0.25% of Total Premium"
    },
    {
        "id": "alternative_accommodation",
        "label": "Alternative accommodation\nUGX 300,000 x days x 10%"
    },
    {
        "id": "car_hire",
        "label": "Car hire\nUGX 100,000 x days x 10%"
    }
]


class MotorPrivateFlow:
    """
    Guided flow for Motor Private.

    Step order:
        0 - about_you
        1 - vehicle_details
        2 - excess_parameters
        3 - additional_benefits
        4 - premium_calculation
        5 - choose_plan_and_pay
    """

    STEPS = [
        "about_you",           # 0
        "vehicle_details",     # 1
        "excess_parameters",   # 2
        "additional_benefits",  # 3
        "premium_calculation",  # 4
        "choose_plan_and_pay",  # 5
    ]

    def __init__(self, product_catalog, db):
        self.catalog = product_catalog
        self.db = db

    @staticmethod
    def _extract_checkbox_ids(payload: Dict[str, Any], *keys: str) -> list[str]:
        """Normalize checkbox payload values into a list of string ids.

        Handles arrays of strings, comma-separated strings, and arrays of objects
        shaped like {id: ...} or {value: ...}.
        """
        raw_value: Any = None
        for key in keys:
            candidate = payload.get(key)
            if candidate:
                raw_value = candidate
                break

        if raw_value is None:
            return []

        if isinstance(raw_value, str):
            items: list[Any] = [s.strip() for s in raw_value.split(",") if s.strip()]
        elif isinstance(raw_value, list):
            items = raw_value
        else:
            items = [raw_value]

        normalized: list[str] = []
        for item in items:
            if isinstance(item, dict):
                value = item.get("id") or item.get("value") or item.get("key") or item.get("name")
                if value is None:
                    continue
                text = str(value).strip()
            else:
                text = str(item).strip()
            if text:
                normalized.append(text)

        return normalized

    # ------------------------------------------------------------------
    # Validation Methods – Pure logic, reusable by both guided flows & APIs
    # ------------------------------------------------------------------

    def _validate_about_you(self, payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, str]]:
        """Validate 'about you' fields. Returns (validated_data, errors)."""
        errors: Dict[str, str] = {}
        validated = {}

        validated["first_name"] = validate_length_range(
            payload.get("first_name", ""),
            field="first_name",
            errors=errors,
            label="First name",
            min_len=2,
            max_len=50,
            required=True,
        )
        validated["middle_name"] = validate_length_range(
            payload.get("middle_name", ""),
            field="middle_name",
            errors=errors,
            label="Middle name",
            min_len=0,
            max_len=50,
            required=False,
        )
        validated["surname"] = validate_length_range(
            payload.get("surname", ""),
            field="surname",
            errors=errors,
            label="Surname",
            min_len=2,
            max_len=50,
            required=True,
        )
        validated["phone_number"] = validate_phone_ug(payload.get("phone_number", ""), errors, field="phone_number")
        validated["email"] = validate_email(payload.get("email", ""), errors, field="email")

        return validated, errors

    def _validate_vehicle_details(self, payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, str]]:
        """Validate vehicle details. Returns (validated_data, errors)."""
        errors: Dict[str, str] = {}
        validated = {}

        validated["cover_type"] = validate_enum(
            payload.get("cover_type", ""),
            field="cover_type",
            errors=errors,
            allowed=["comprehensive", "third_party"],
            required=True,
            message="Please select a cover type.",
        )
        validated["vehicle_make"] = validate_enum(
            payload.get("vehicle_make", ""),
            field="vehicle_make",
            errors=errors,
            allowed=[
                "Toyota",
                "Nissan",
                "Honda",
                "Subaru",
                "Suzuki",
                "Mazda",
                "Mitsubishi",
                "Isuzu",
                "Ford",
                "Hyundai",
                "Kia",
                "Volkswagen",
                "Mercedes-Benz",
                "BMW",
                "Peugeot",
                "Renault",
                "Other",
            ],
            required=True,
            message="Please select a valid vehicle make.",
        )

        year_val = payload.get("year_of_manufacture", "")
        try:
            validated["year_of_manufacture"] = int(year_val)
            current_year = date.today().year
            if not (1980 <= validated["year_of_manufacture"] <= current_year):
                errors["year_of_manufacture"] = "Year must be between 1980 and the current year."
        except (ValueError, TypeError):
            errors["year_of_manufacture"] = "Year must be a valid integer."
            validated["year_of_manufacture"] = None

        validated["cover_start_date"] = validate_cover_start_date_range(
            payload.get("cover_start_date", ""),
            errors,
            field="cover_start_date",
        )

        validated["is_rare_model"] = validate_enum(
            payload.get("is_rare_model", ""),
            field="is_rare_model",
            errors=errors,
            allowed=["yes", "no"],
            required=True,
            message="Please select if the vehicle is a rare model.",
        )
        validated["has_undergone_valuation"] = validate_enum(
            payload.get("has_undergone_valuation", ""),
            field="has_undergone_valuation",
            errors=errors,
            allowed=["yes", "no"],
            required=True,
            message="Please indicate if the vehicle has undergone valuation.",
        )

        vehicle_value = payload.get("vehicle_value_ugx", "")
        try:
            validated["vehicle_value_ugx"] = float(vehicle_value)
            if not (10_000_000 <= validated["vehicle_value_ugx"] <= 100_000_000):
                errors["vehicle_value_ugx"] = "Vehicle value must be between UGX 10,000,000 and UGX 100,000,000."
        except (ValueError, TypeError):
            errors["vehicle_value_ugx"] = "Vehicle value must be a valid number between UGX 10,000,000 and UGX 100,000,000."
            validated["vehicle_value_ugx"] = None

        return validated, errors

    def _validate_excess_parameters(self, payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, str]]:
        """Validate excess parameters. Returns (validated_data, errors)."""
        errors: Dict[str, str] = {}
        validated = {}

        allowed_ids = {p["id"] for p in MOTOR_PRIVATE_EXCESS_PARAMETERS}
        selected = self._extract_checkbox_ids(payload, "excess_parameters", "excess_choice", "risky_activities")
        cleaned = []
        seen = set()
        for item in selected:
            if item in allowed_ids and item not in seen:
                cleaned.append(item)
                seen.add(item)

        validated["excess_choice"] = cleaned

        return validated, errors

    def _validate_additional_benefits(self, payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, str]]:
        """Validate additional benefits. Returns (validated_data, errors)."""
        errors: Dict[str, str] = {}
        validated = {}

        selected = self._extract_checkbox_ids(payload, "additional_benefits", "risky_activities")
        allowed_ids = {b["id"] for b in MOTOR_PRIVATE_ADDITIONAL_BENEFITS}
        cleaned = []
        seen = set()
        invalid = []
        for item in selected:
            if item in allowed_ids:
                if item not in seen:
                    cleaned.append(item)
                    seen.add(item)
            else:
                invalid.append(item)

        if invalid:
            errors["additional_benefits"] = f"Invalid selections: {', '.join(invalid)}"

        validated["selected_benefits"] = cleaned
        return validated, errors

    def _build_motor_runtime_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Merge full-form and guided-step state into one runtime view for preview/quoting."""
        runtime = dict(data.get("motor_frontend", {}) or {})
        vehicle_details = data.get("vehicle_details", {}) or {}
        about_you = data.get("about_you", {}) or {}

        runtime.setdefault("vehicle_make", vehicle_details.get("vehicle_make", ""))
        runtime.setdefault("year_of_manufacture", vehicle_details.get("year_of_manufacture", ""))
        runtime.setdefault("cover_start_date", vehicle_details.get("cover_start_date", ""))
        runtime.setdefault("rare_model", vehicle_details.get("rare_model", "no"))
        runtime.setdefault("valuation_done", vehicle_details.get("valuation_done", "no"))
        runtime.setdefault("vehicle_value", vehicle_details.get("vehicle_value", 0))
        runtime.setdefault("first_time_registration", vehicle_details.get("first_time_registration", "No"))
        runtime.setdefault("car_alarm_installed", vehicle_details.get("car_alarm_installed", "No"))
        runtime.setdefault("tracking_system_installed", vehicle_details.get("tracking_system_installed", "No"))
        runtime.setdefault("car_usage_region", vehicle_details.get("car_usage_region", "Within Uganda"))
        runtime.setdefault("cover_type", vehicle_details.get("cover_type", runtime.get("cover_type", "comprehensive")))
        runtime.setdefault("first_name", about_you.get("first_name", runtime.get("first_name", "")))
        runtime.setdefault("middle_name", about_you.get("middle_name", runtime.get("middle_name", "")))
        runtime.setdefault("surname", about_you.get("surname", runtime.get("surname", "")))
        runtime.setdefault("phone_number", about_you.get("phone_number", runtime.get("phone_number", "")))
        runtime.setdefault("email", about_you.get("email", runtime.get("email", "")))
        runtime.setdefault("selected_benefits", data.get("additional_benefits", runtime.get("selected_benefits", [])))
        runtime.setdefault("excess_choice", data.get("excess_parameters", runtime.get("excess_choice", [])))

        return runtime

    def _build_motor_premium_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Map guided-flow state into the premium engine input shape."""
        runtime = self._build_motor_runtime_data(data)
        return {
            "vehicle_value_ugx": runtime.get("vehicle_value") or runtime.get("vehicle_value_ugx") or runtime.get("vehicleValueUgx") or 32_000_000,
            "car_usage_region": runtime.get("car_usage_region") or runtime.get("regionBounds") or "Within Uganda",
            "first_time_registration": runtime.get("first_time_registration") or runtime.get("firstApplication") or "No",
            "car_alarm_installed": runtime.get("car_alarm_installed") or runtime.get("alarmDiscountRate") or "No",
            "tracking_system_installed": runtime.get("tracking_system_installed") or runtime.get("trackerDiscountRate") or "No",
            "selected_benefits": runtime.get("selected_benefits") or data.get("additional_benefits") or [],
            "excess_choice": runtime.get("excess_choice") or data.get("excess_parameters") or [],
            "cover_start_date": runtime.get("cover_start_date") or runtime.get("coverStartDate") or "",
            "year_of_manufacture": runtime.get("year_of_manufacture") or runtime.get("yearOfManufacture") or "",
            "first_name": runtime.get("first_name") or "",
            "middle_name": runtime.get("middle_name") or "",
            "surname": runtime.get("surname") or "",
            "email": runtime.get("email") or "",
            "vehicle_make": runtime.get("vehicle_make") or "",
            "vehicle_model": runtime.get("vehicle_model") or "",
        }

    def _build_motor_preview_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Map flow state into the mock underwriting preview shape."""
        premium_payload = self._build_motor_premium_payload(data)
        runtime = self._build_motor_runtime_data(data)
        return {
            "vehicle_value_ugx": premium_payload["vehicle_value_ugx"],
            "vehicleValue": str(premium_payload["vehicle_value_ugx"]),
            "vehicle_make": premium_payload["vehicle_make"],
            "vehicleMake": premium_payload["vehicle_make"],
            "year_of_manufacture": premium_payload["year_of_manufacture"],
            "yearOfManufacture": str(premium_payload["year_of_manufacture"]),
            "cover_type": runtime.get("cover_type", "comprehensive"),
            "coverType": runtime.get("cover_type", "comprehensive"),
            "cover_start_date": premium_payload["cover_start_date"],
            "policyStartDate": premium_payload["cover_start_date"],
            "car_usage_region": premium_payload["car_usage_region"],
            "first_time_registration": premium_payload["first_time_registration"],
            "car_alarm_installed": premium_payload["car_alarm_installed"],
            "tracking_system_installed": premium_payload["tracking_system_installed"],
            "selected_benefits": premium_payload["selected_benefits"],
            "excess_choice": premium_payload["excess_choice"],
            "rareModel": runtime.get("rare_model", "no"),
        }

    # ------------------------------------------------------------------
    # complete_flow – convenience helper (skips step-by-step UI)
    # ------------------------------------------------------------------

    async def complete_flow(self, collected_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """Finalize the flow from already-collected data."""
        data = dict(collected_data or {})
        payload = data.copy()
        errors: Dict[str, str] = {}

        # ── Personal Details (frontend field names) ────────────────────
        first_name = None
        surname = None
        middle_name = None
        mobile_original = None
        mobile_normalized = None
        email = None
        if "firstName" in payload or "surname" in payload or "mobile" in payload or "email" in payload:
            first_name = validate_length_range(
                payload.get("firstName", ""),
                field="firstName",
                errors=errors,
                label="First name",
                min_len=2,
                max_len=50,
                required=True,
                message="First name must be 2–50 characters.",
            )
            middle_name = validate_length_range(
                payload.get("middleName", ""),
                field="middleName",
                errors=errors,
                label="Middle name",
                min_len=0,
                max_len=50,
                required=False,
                message="Middle name must be up to 50 characters.",
            )
            surname = validate_length_range(
                payload.get("surname", ""),
                field="surname",
                errors=errors,
                label="Surname",
                min_len=2,
                max_len=50,
                required=True,
                message="Surname must be 2–50 characters.",
            )
            mobile_original, mobile_normalized = validate_uganda_mobile_frontend(
                payload.get("mobile", ""), errors, field="mobile"
            )
            email = validate_motor_email_frontend(payload.get("email", ""), errors, field="email")

        # ── Cover type ─────────────────────────────────────────────────
        cover_type = None
        if "coverType" in payload:
            cover_type = validate_enum(
                payload.get("coverType", ""),
                field="coverType",
                errors=errors,
                allowed=["comprehensive", "third_party"],
                required=True,
                message="Please select a cover type.",
            )

        # ── Vehicle / premium fields (frontend field names) ────────────
        vehicle_make_frontend = None
        year_frontend = None
        cover_start_frontend = None
        rare_model_frontend = None
        valuation_frontend = None
        vehicle_value_frontend = None
        if "vehicleMake" in payload or "yearOfManufacture" in payload or "coverStartDate" in payload:
            vehicle_make_frontend = require_str(payload, "vehicleMake", errors, label="Vehicle make")
            current_year = date.today().year
            year_frontend = parse_int(
                {"yearOfManufacture": payload.get("yearOfManufacture")},
                "yearOfManufacture",
                errors,
                min_value=1980,
                max_value=current_year,
                required=True,
            )
            cover_start_frontend = validate_cover_start_date_range(
                payload.get("coverStartDate", ""), errors, field="coverStartDate"
            )
            rare_model_frontend = validate_enum(
                payload.get("isRareModel", ""),
                field="isRareModel",
                errors=errors,
                allowed=["yes", "no"],
                required=True,
                message="Please select if the vehicle is a rare model.",
            )
            valuation_frontend = validate_enum(
                payload.get("hasUndergoneValuation", ""),
                field="hasUndergoneValuation",
                errors=errors,
                allowed=["yes", "no"],
                required=True,
                message="Please indicate if the vehicle has undergone valuation.",
            )
            vehicle_value_raw = str(payload.get("vehicleValueUgx", "")).strip()
            try:
                vehicle_value_frontend = float(vehicle_value_raw)
                if not (10_000_000 <= vehicle_value_frontend <= 100_000_000):
                    errors["vehicleValueUgx"] = "Vehicle value must be between UGX 10,000,000 and UGX 100,000,000."
            except (ValueError, TypeError):
                errors["vehicleValueUgx"] = "Vehicle value must be a valid number between UGX 10,000,000 and UGX 100,000,000."
                vehicle_value_frontend = None

        raise_if_errors(errors)

        # ── Map into internal structure ────────────────────────────────
        internal = data.setdefault("motor_frontend", {})
        if cover_type is not None:
            internal["cover_type"] = cover_type
        if first_name is not None:
            internal["first_name"] = first_name
        if middle_name is not None:
            internal["middle_name"] = middle_name
        if surname is not None:
            internal["surname"] = surname
        if mobile_original is not None:
            internal["mobile"] = mobile_original
        if mobile_normalized:
            internal["mobile_normalized"] = mobile_normalized
        if email is not None:
            internal["email"] = email
        if vehicle_make_frontend is not None:
            internal["vehicle_make"] = vehicle_make_frontend
        if year_frontend is not None:
            internal["year_of_manufacture"] = year_frontend
        if cover_start_frontend is not None:
            internal["cover_start_date"] = cover_start_frontend
        if rare_model_frontend is not None:
            internal["rare_model"] = rare_model_frontend
        if valuation_frontend is not None:
            internal["valuation_done"] = valuation_frontend
        if vehicle_value_frontend is not None:
            internal["vehicle_value"] = vehicle_value_frontend

        data.setdefault("user_id", user_id)
        data.setdefault("product_id", "motor_private")

        # ── Run all steps in order ─────────────────────────────────────
        step_handlers = [
            self._step_about_you,
            self._step_vehicle_details,
            self._step_excess_parameters,
            self._step_additional_benefits,
            self._step_premium_calculation,
            self._step_choose_plan_and_pay,
        ]
        result = {}
        for i, handler in enumerate(step_handlers):
            step_payload = {} if i != len(step_handlers) - 1 else {"action": "proceed_to_pay"}
            result = await handler(step_payload, data, user_id)
            if "collected_data" in result:
                data = result["collected_data"]

        result.setdefault("status", "success")
        return result

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    async def start(self, user_id: str, initial_data: Dict) -> Dict:
        data = dict(initial_data or {})
        data.setdefault("user_id", user_id)
        data.setdefault("product_id", "motor_private")
        return await self.process_step("", 0, data, user_id)

    async def process_step(
        self,
        user_input: str,
        current_step: int,
        collected_data: Dict[str, Any],
        user_id: str,
    ) -> Dict:
        try:
            if user_input and isinstance(user_input, str) and user_input.strip().startswith("{"):
                payload = json.loads(user_input)
            elif user_input and isinstance(user_input, dict):
                payload = user_input
            else:
                payload = {"_raw": user_input} if user_input else {}
        except (json.JSONDecodeError, TypeError):
            payload = {"_raw": user_input} if user_input else {}

        handlers = {
            0: self._step_about_you,
            1: self._step_vehicle_details,
            2: self._step_excess_parameters,
            3: self._step_additional_benefits,
            4: self._step_premium_calculation,
            5: self._step_choose_plan_and_pay,
        }
        handler = handlers.get(current_step)
        if handler is None:
            return {"error": "Invalid step"}
        return await handler(payload, collected_data, user_id)

    # ------------------------------------------------------------------
    # Step 0 – About You
    # ------------------------------------------------------------------

    async def _step_about_you(self, payload: Dict, data: Dict, user_id: str) -> Dict:
        try:
            if payload and "_raw" not in payload:
                validated, errors = self._validate_about_you(payload)
                raise_if_errors(errors)

                # If no errors, save and proceed
                data["about_you"] = validated
                out = await self._step_vehicle_details({}, data, user_id)
                out["next_step"] = 1
                return out
        except Exception as e:
            if "Please correct" in str(e):  # FormValidationError
                raise
            return {"error": f"Exception in about_you: {str(e)}", "step": "about_you"}

        errors = {}
        validated, _ = self._validate_about_you(payload)

        # Pre-fill from existing data
        prefilled = data.get("about_you", {})

        # Define all fields
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
                "maxLength": 12,
                "inputMode": "numeric",
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

        # Filter to show only missing or invalid fields
        filtered_fields = filter_missing_fields(
            all_fields=all_fields,
            payload=payload,
            collected_data=data,
            validation_errors=errors,
            data_key="about_you"
        )

        # Add validation hints and frontend rules
        fields_with_validation = FieldDecorator.decorate(filtered_fields, errors=errors)

        return {
            "response": {
                "type": "form",
                "message": "About You" + (" - Please fix the errors below" if errors else ""),
                "fields": fields_with_validation,
            },
            "next_step": 1,          # ✅ Fixed: was incorrectly 6
            "collected_data": data,
        }

    # ------------------------------------------------------------------
    # Step 1 – Vehicle Details
    # ------------------------------------------------------------------

    async def _step_vehicle_details(self, payload: Dict, data: Dict, user_id: str) -> Dict:
        errors: Dict[str, str] = {}
        try:
            if payload and "_raw" not in payload:
                vehicle_make = require_str(payload, "vehicle_make", errors, label="Vehicle make")
                year = parse_int(
                    payload,
                    "year_of_manufacture",
                    errors,
                    min_value=1980,
                    max_value=date.today().year,
                    required=True,
                )
                cover_start_date = validate_cover_start_date_range(
                    payload.get("cover_start_date", ""), errors, field="cover_start_date"
                )
                rare_model = validate_in(
                    payload.get("rare_model", ""),
                    {"Yes", "No"},
                    errors,
                    "rare_model",
                    required=True,
                )
                valuation_done = validate_in(
                    payload.get("valuation_done", ""),
                    {"Yes", "No"},
                    errors,
                    "valuation_done",
                    required=True,
                )
                vehicle_value_raw = str(payload.get("vehicle_value", "")).strip()
                vehicle_value = vehicle_value_raw
                if not vehicle_value_raw:
                    errors["vehicle_value"] = "Vehicle value must be between UGX 10,000,000 and UGX 100,000,000."
                else:
                    try:
                        vehicle_value_num = float(vehicle_value_raw)
                        if not (10_000_000 <= vehicle_value_num <= 100_000_000):
                            errors["vehicle_value"] = "Vehicle value must be between UGX 10,000,000 and UGX 100,000,000."
                    except (ValueError, TypeError):
                        errors["vehicle_value"] = "Vehicle value must be a valid number between UGX 10,000,000 and UGX 100,000,000."
                first_time_registration = validate_in(
                    payload.get("first_time_registration", ""),
                    {"Yes", "No"},
                    errors,
                    "first_time_registration",
                    required=True,
                )
                car_alarm_installed = validate_in(
                    payload.get("car_alarm_installed", ""),
                    {"Yes", "No"},
                    errors,
                    "car_alarm_installed",
                    required=True,
                )
                tracking_system_installed = validate_in(
                    payload.get("tracking_system_installed", ""),
                    {"Yes", "No"},
                    errors,
                    "tracking_system_installed",
                    required=True,
                )
                car_usage_region = validate_in(
                    payload.get("car_usage_region", ""),
                    {"Within Uganda", "Within East Africa", "Outside East Africa"},
                    errors,
                    "car_usage_region",
                    required=True,
                )
                raise_if_errors(errors)
                vehicle_details = {
                    "vehicle_make": vehicle_make,
                    "year_of_manufacture": str(year),
                    "cover_start_date": cover_start_date,
                    "rare_model": rare_model,
                    "valuation_done": valuation_done,
                    "vehicle_value": vehicle_value,
                    "first_time_registration": first_time_registration,
                    "car_alarm_installed": car_alarm_installed,
                    "tracking_system_installed": tracking_system_installed,
                    "car_usage_region": car_usage_region,
                }
                data["vehicle_details"] = vehicle_details
                motor_frontend = data.setdefault("motor_frontend", {})
                motor_frontend.update(vehicle_details)
                out = await self._step_excess_parameters({}, data, user_id)
                out["next_step"] = 2
                return out
        except Exception as e:
            if "Please correct" in str(e):
                raise
            return {"error": f"Exception in vehicle_details: {str(e)}", "step": "vehicle_details"}

        prefilled = data.get("vehicle_details", {})
        fields = [
            {
                "name": "vehicle_make",
                "label": "Choose vehicle make",
                "type": "select",
                "required": True,
                "defaultValue": (payload or {}).get("vehicle_make", prefilled.get("vehicle_make", "")),
                "options": [
                    "Toyota", "Nissan", "Honda", "Subaru", "Suzuki",
                    "Mazda", "Mitsubishi", "Isuzu", "Ford", "Hyundai",
                    "Kia", "Volkswagen", "Mercedes-Benz", "BMW",
                    "Peugeot", "Renault", "Other"
                ],
            },
            {
                "name": "year_of_manufacture",
                "label": "Year of manufacture",
                "type": "select",
                "required": True,
                "options": [str(y) for y in range(date.today().year, 1979, -1)],
                "defaultValue": (payload or {}).get("year_of_manufacture", prefilled.get("year_of_manufacture", "")),
            },
            {
                "name": "cover_start_date",
                "label": "Cover start date",
                "type": "date",
                "required": True,
                "defaultValue": (payload or {}).get("cover_start_date", prefilled.get("cover_start_date", "")),
            },
            {
                "name": "rare_model",
                "label": "Is the car a rare model?",
                "type": "radio",
                "options": ["Yes", "No"],
                "required": True,
                "defaultValue": (payload or {}).get("rare_model", prefilled.get("rare_model", "")),
            },
            {
                "name": "valuation_done",
                "label": "Has the vehicle undergone valuation?",
                "type": "radio",
                "options": ["Yes", "No"],
                "required": True,
                "defaultValue": (payload or {}).get("valuation_done", prefilled.get("valuation_done", "")),
            },
            {
                "name": "vehicle_value",
                "label": "Value of Vehicle (UGX)",
                "type": "number",
                "required": True,
                "min": 10000000,
                "max": 100000000,
                "inputMode": "numeric",
                "defaultValue": (payload or {}).get("vehicle_value", prefilled.get("vehicle_value", "")),
            },
            {
                "name": "first_time_registration",
                "label": "First time this vehicle is registered for this type of insurance?",
                "type": "radio",
                "options": ["Yes", "No"],
                "required": True,
                "defaultValue": (payload or {}).get("first_time_registration", prefilled.get("first_time_registration", "")),
            },
            {
                "name": "car_alarm_installed",
                "label": "Do you have a car alarm installed?",
                "type": "radio",
                "options": ["Yes", "No"],
                "required": True,
                "defaultValue": (payload or {}).get("car_alarm_installed", prefilled.get("car_alarm_installed", "")),
            },
            {
                "name": "tracking_system_installed",
                "label": "Do you have a tracking system installed?",
                "type": "radio",
                "options": ["Yes", "No"],
                "required": True,
                "defaultValue": (payload or {}).get("tracking_system_installed", prefilled.get("tracking_system_installed", "")),
            },
            {
                "name": "car_usage_region",
                "label": "Car usage: within Uganda, East Africa, or outside East Africa?",
                "type": "radio",
                "options": ["Within Uganda", "Within East Africa", "Outside East Africa"],
                "required": True,
                "defaultValue": (payload or {}).get("car_usage_region", prefilled.get("car_usage_region", "")),
            },
        ]
        fields_with_validation = FieldDecorator.decorate(fields, errors=errors)

        return {
            "response": {
                "type": "form",
                "message": "Premium Calculation - Vehicle Details",
                "fields": fields_with_validation,
            },
            "next_step": 2,          # ✅ Fixed: was incorrectly 1
            "collected_data": data,
        }

    # ------------------------------------------------------------------
    # Step 2 – Excess Parameters
    # ------------------------------------------------------------------

    async def _step_excess_parameters(self, payload: Dict, data: Dict, user_id: str) -> Dict:
        try:
            if payload and "_raw" not in payload:
                selected = self._extract_checkbox_ids(
                    payload,
                    "excess_parameters",
                    "excess_choice",
                    "risky_activities",
                )
                allowed_ids = {p["id"] for p in MOTOR_PRIVATE_EXCESS_PARAMETERS}
                cleaned = []
                seen = set()
                for item in selected:
                    if item in allowed_ids and item not in seen:
                        cleaned.append(item)
                        seen.add(item)
                data["excess_parameters"] = cleaned
                out = await self._step_additional_benefits({}, data, user_id)
                out["next_step"] = 3
                return out
        except Exception as e:
            if "Please correct" in str(e):
                raise
            return {"error": f"Exception in excess_parameters: {str(e)}", "step": "excess_parameters"}

        return {
            "response": {
                "type": "checkbox",
                "name": "excess_parameters",
                "message": "Select your deductible option (your contribution before insurer payout)",
                "options": MOTOR_PRIVATE_EXCESS_PARAMETERS,
                "defaultValue": data.get("excess_parameters", []),
            },
            "next_step": 3,          # ✅ Correct
            "collected_data": data,
        }

    # ------------------------------------------------------------------
    # Step 3 – Additional Benefits
    # ------------------------------------------------------------------

    async def _step_additional_benefits(self, payload: Dict, data: Dict, user_id: str) -> Dict:
        try:
            if payload and "_raw" not in payload:
                selected = self._extract_checkbox_ids(
                    payload,
                    "additional_benefits",
                    "risky_activities",
                )

                allowed_ids = {b["id"] for b in MOTOR_PRIVATE_ADDITIONAL_BENEFITS}
                # Frontend may send mixed checkbox payloads; keep only valid benefit IDs.
                cleaned = []
                seen = set()
                for item in selected:
                    if item in allowed_ids and item not in seen:
                        cleaned.append(item)
                        seen.add(item)
                data["additional_benefits"] = cleaned
                out = await self._step_premium_calculation({}, data, user_id)
                out["next_step"] = 4
                return out
        except Exception as e:
            if "Please correct" in str(e):
                raise
            return {"error": f"Exception in additional_benefits: {str(e)}", "step": "additional_benefits"}

        return {
            "response": {
                "type": "checkbox",
                "name": "additional_benefits",
                "message": "Additional Benefits",
                "options": MOTOR_PRIVATE_ADDITIONAL_BENEFITS,
                "defaultValue": data.get("additional_benefits", []),
            },
            "next_step": 4,
            "collected_data": data,
        }

    # ------------------------------------------------------------------
    # Background helper – load product benefits into data silently
    # ------------------------------------------------------------------

    def _load_benefits(self, data: Dict) -> None:
        """Populate data['benefits'] from product config without showing a UI step."""
        data["benefits"] = product_benefits_loader.get_benefits_as_dict("motor_private", 0)

    # ------------------------------------------------------------------
    # Step 4 – Premium Calculation (display + advance to pay)
    # ------------------------------------------------------------------

    async def _step_premium_calculation(self, payload: Dict, data: Dict, user_id: str) -> Dict:
        try:
            if payload and "_raw" not in payload:
                action = (payload.get("action") or payload.get("type") or payload.get("_raw") or "").strip().lower()
                if any(token in action for token in ("proceed_to_pay", "proceed", "continue", "pay", "buy")):
                    out = await self._step_choose_plan_and_pay({"action": "proceed_to_pay"}, data, user_id)
                    out["next_step"] = 5
                    return out
                if "edit" in action or "back" in action:
                    out = await self._step_about_you({}, data, user_id)
                    out["next_step"] = 0
                    return out
                # For download/unknown actions, stay on this step and return summary again.
        except Exception as e:
            return {"error": f"Exception in premium_calculation: {str(e)}", "step": "premium_calculation"}

        # Load benefits silently into data for downstream use (PDF, API, etc.)
        self._load_benefits(data)

        # Calculate premium
        premium = self._calculate_motor_private_premium(data)
        data["_cached_motor_private_premium"] = dict(premium)

        # Attempt a non-destructive quotation preview from the underwriting pipeline
        # This is used to display mocked quotation information to the user while
        # the flow continues to collect remaining details before payment
        quotation_preview = None
        try:
            preview_result = await run_quote_preview(
                user_id=user_id,
                product_id="motor_private",
                underwriting_data=self._build_motor_preview_payload(data),
                currency="UGX",
            )
            quotation_preview = preview_result.get("quotation") if preview_result else None
            if quotation_preview:
                data["preview_quotation"] = quotation_preview
        except Exception:
            quotation_preview = None

        resp = {
            "response": {
                "type": "premium_summary",
                "message": "Motor Private Premium",
                "product_name": "Motor Private",
                "quote_summary": premium,
                "download_option": True,
                "download_label": "Download Quote (PDF)",
                "actions": [
                    {"type": "download_quote", "label": "Download Quote"},
                    {"type": "proceed_to_pay", "label": "Proceed to Pay"},
                ],
            },
            "next_step": 5,
            "collected_data": data,
        }

        quote_id = ""
        if quotation_preview:
            resp["response"]["quotation_preview"] = quotation_preview
            resp["response"]["payable_amount"] = quotation_preview.get("payable_amount")
            quote_id = str(quotation_preview.get("quote_id") or "").strip()

        try:
            quotation = build_motor_private_quotation(data, quote_id or None)
            quote_id = quote_id or str(quotation.get("quote_number") or "").strip()
            if quote_id:
                resp["response"]["quote_id"] = quote_id
                resp["response"]["download_url"] = register_quote_pdf(
                    quote_id,
                    generate_motor_private_quote_pdf(quotation),
                    metadata={"product_name": "Motor Private"},
                )
        except Exception:
            # Keep premium summary flow resilient even if quote-PDF generation fails.
            pass

        return resp

    # ------------------------------------------------------------------
    # Step 5 – Choose Plan & Pay
    # ------------------------------------------------------------------

    async def _step_choose_plan_and_pay(self, payload: Dict, data: Dict, user_id: str) -> Dict:
        try:
            action = (payload.get("action") or payload.get("type") or payload.get("_raw") or "").strip().lower()
            if "edit" in action:
                out = await self._step_about_you({}, data, user_id)
                out["next_step"] = 0   # ✅ Send user back to beginning of flow
                return out
            if "download" in action and "proceed" not in action and "pay" not in action:
                out = await self._step_premium_calculation({}, data, user_id)
                out["next_step"] = 4
                return out

            premium = self._calculate_motor_private_premium(data)
            quote = self.db.create_quote(
                user_id=user_id,
                product_id=data.get("product_id", "motor_private"),
                premium_amount=premium["total"],
                sum_assured=None,
                underwriting_data=data,
                pricing_breakdown=premium,
                product_name="Motor Private",
            )
            data["quote_id"] = str(quote.id)
        except Exception as e:
            return {"error": f"Exception in choose_plan_and_pay: {str(e)}", "step": "choose_plan_and_pay"}

        return {
            "response": {
                "type": "proceed_to_payment",
                "message": "Proceeding to payment. Choose your payment method.",
                "quote_id": str(quote.id),
            },
            "complete": True,
            "next_flow": "payment",
            "collected_data": data,
            "data": {"quote_id": str(quote.id)},
        }

    # ------------------------------------------------------------------
    # Premium calculation helper
    # ------------------------------------------------------------------

    def _calculate_motor_private_premium(self, data: Dict) -> Dict:
        """Calculate Motor Private premium. Replace with actual business logic as needed."""
        premium_payload = self._build_motor_premium_payload(data)
        result = premium_service.calculate_sync("motor_private", {"data": premium_payload})
        if "sticker_fees" not in result and "sticker_fee" in result:
            result["sticker_fees"] = result["sticker_fee"]
        return result
