"""
Serenicare flow - Collect user details first, then plan selection, optional benefits,
medical conditions, cover personalization, and proceed to payment.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict

from src.chatbot.field_validator import FieldDecorator
from src.chatbot.validation import (
    validate_date_iso,
    validate_length_range,
    validate_motor_email_frontend,
    validate_uganda_mobile_frontend,
)
from src.integrations.clients.mocks.product_logic.serenicare_insurance import SerenicarePremuimService
from src.integrations.quote_generation import generate_and_register_quote_pdf


premium_service = SerenicarePremuimService()

SERENICARE_OPTIONAL_BENEFITS = [
    {
        "id": "outpatient",
        "label": "Outpatient",
        "description": (
            "Clinic visits, diagnostics, and treatments without a hospital stay "
            "(Up to UGX 3,000,000.00 per person)"
        ),
    },
    {
        "id": "maternity",
        "label": "Maternity Cover",
        "description": (
            "Maternity benefits for checkups, scans, delivery, and immediate newborn care "
            "(Up to UGX 3,000,000.00 per family)"
        ),
    },
    {
        "id": "dental",
        "label": "Dental Cover",
        "description": (
            "Dental treatment for checkups, X-rays, fillings, and extractions "
            "(Up to UGX 300,000.00 per person)"
        ),
    },
    {
        "id": "optical",
        "label": "Optical Cover",
        "description": (
            "Vision care including eye tests, prescription glasses or contact lenses "
            "(Up to UGX 350,000.00 per person)"
        ),
    },
    {
        "id": "covid19",
        "label": "COVID-19 Cover",
        "description": "Care for COVID-19 from diagnosis to recovery",
    },
]

SERENICARE_PLANS = [
    {
        "id": "essential",
        "label": "Essential",
        "description": "Reliable coverage with fundamental limits, offering value and security.",
        "benefits": {
            "Inpatient limit per family": "UGX 15,000,000",
            "Outpatient limit per person": "UGX 1,500,000",
            "Maternity cover per family": "UGX 1,500,000",
            "Optical limit per person": "UGX 200,000",
            "Dental limit per person": "UGX 150,000",
        },
    },
    {
        "id": "classic",
        "label": "Classic",
        "description": "A balanced choice, delivering broader coverage with standout benefits.",
        "benefits": {
            "Inpatient limit per family": "UGX 30,000,000",
            "Outpatient limit per person": "UGX 2,000,000",
            "Maternity cover per family": "UGX 2,500,000",
            "Optical limit per person": "UGX 300,000",
            "Dental limit per person": "UGX 200,000",
        },
    },
    {
        "id": "comprehensive",
        "label": "Comprehensive",
        "description": "Expansive coverage with high limits for extensive health security.",
        "benefits": {
            "Inpatient limit per family": "UGX 60,000,000",
            "Outpatient limit per person": "UGX 3,000,000",
            "Maternity cover per family": "UGX 3,000,000",
            "Optical limit per person": "UGX 350,000",
            "Dental limit per person": "UGX 300,000",
        },
    },
    {
        "id": "premium",
        "label": "Premium",
        "description": "Ultimate health protection for those demanding the best healthcare.",
        "benefits": {
            "Inpatient limit per family": "UGX 100,000,000",
            "Outpatient limit per person": "UGX 5,000,000",
            "Maternity cover per family": "UGX 4,000,000",
            "Optical limit per person": "UGX 400,000",
            "Dental limit per person": "UGX 400,000",
        },
    },
]


class SerenicareFlow:
    """
    Guided flow for Serenicare: about you, plan selection, optional benefits,
    medical conditions, cover personalization, then payment.
    """

    STEPS = [
        "about_you",
        "plan_selection",
        "optional_benefits",
        "medical_conditions",
        "cover_personalization",
        "premium_and_download",
        "choose_plan_and_pay",
    ]

    def __init__(self, product_catalog, db):
        self.catalog = product_catalog
        self.db = db
        try:
            from src.chatbot.controllers.serenicare_controller import SerenicareController

            self.controller = SerenicareController(db)
        except Exception:
            self.controller = None

    # -------------------------------------------------------------------------
    # VALIDATION METHODS – Pure logic, reusable by guided flows & APIs
    # -------------------------------------------------------------------------

    @staticmethod
    def _age_from_iso_dob(dob_iso: str) -> int | None:
        if not dob_iso:
            return None
        try:
            dob = date.fromisoformat(str(dob_iso))
        except (ValueError, TypeError):
            return None
        today = date.today()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    def _validate_about_you(self, payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, str]]:
        """Validate 'about you' fields. Returns (validated_data, errors)."""
        errors: Dict[str, str] = {}
        validated = {}

        validated["first_name"] = validate_length_range(
            payload.get("first_name", ""),
            field="first_name",
            errors=errors,
            label="First Name",
            min_len=2,
            max_len=50,
            required=True,
        )
        validated["middle_name"] = validate_length_range(
            payload.get("middle_name", ""),
            field="middle_name",
            errors=errors,
            label="Middle Name",
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
        _, validated["phone_number"] = validate_uganda_mobile_frontend(
            payload.get("phone_number", ""), errors, field="phone_number"
        )
        validated["email"] = validate_motor_email_frontend(payload.get("email", ""), errors, field="email")

        return validated, errors

    def _validate_plan_selection(self, payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, str]]:
        """Validate plan selection. Returns (validated_data, errors)."""
        errors: Dict[str, str] = {}
        validated = {}

        plan_id = (payload.get("plan_option") or payload.get("_raw") or "").strip()
        if not plan_id:
            errors["plan_option"] = "Plan selection is required."

        allowed_ids = [p["id"] for p in SERENICARE_PLANS]
        if plan_id and plan_id not in allowed_ids:
            errors["plan_option"] = f"Invalid plan. Allowed: {', '.join(allowed_ids)}"

        validated["plan_option"] = {"id": plan_id} if plan_id else {}
        return validated, errors

    def _validate_optional_benefits(self, payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, str]]:
        """Validate optional benefits selection. Returns (validated_data, errors)."""
        errors: Dict[str, str] = {}
        validated = {}

        selected = payload.get("optional_benefits") or []
        if isinstance(selected, str):
            selected = [s.strip() for s in selected.split(",") if s.strip()]

        allowed_benefits = ["outpatient", "maternity", "dental", "optical", "covid19"]
        invalid = [s for s in selected if s not in allowed_benefits]
        if invalid:
            errors["optional_benefits"] = f"Invalid benefits: {', '.join(invalid)}"

        validated["selected_benefits"] = [s for s in selected if s not in invalid]
        return validated, errors

    def _validate_medical_conditions(self, payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, str]]:
        """Validate medical conditions declaration. Returns (validated_data, errors)."""
        errors: Dict[str, str] = {}
        validated = {}

        has_condition = payload.get("has_condition") in (True, "yes", "true", "1", 1)
        validated["has_condition"] = has_condition

        return validated, errors

    def _validate_cover_personalization(self, payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, str]]:
        """Validate cover personalization (DOB, family members). Returns (validated_data, errors)."""
        errors: Dict[str, str] = {}
        validated = {}

        dob = validate_date_iso(payload.get("date_of_birth", ""), errors, "date_of_birth", required=True, not_future=True)
        age = self._age_from_iso_dob(dob)
        if dob and age is not None and age < 18:
            errors["date_of_birth"] = "You must be at least 18 years old."
        validated["date_of_birth"] = dob

        include_spouse = payload.get("include_spouse", False) in (True, "yes", "true", "1")
        include_children = payload.get("include_children", False) in (True, "yes", "true", "1")
        add_another_main_member = payload.get("add_another_main_member", False) in (True, "yes", "true", "1")

        validated["include_spouse"] = include_spouse
        validated["include_children"] = include_children
        validated["add_another_main_member"] = add_another_main_member
        validated["spouse_dob"] = validate_date_iso(
            payload.get("spouse_dob", ""),
            errors,
            "spouse_dob",
            required=include_spouse,
            not_future=True,
        )
        validated["child_dob"] = validate_date_iso(
            payload.get("child_dob", ""),
            errors,
            "child_dob",
            required=include_children,
            not_future=True,
        )
        validated["other_member_dob"] = validate_date_iso(
            payload.get("other_member_dob", ""),
            errors,
            "other_member_dob",
            required=add_another_main_member,
            not_future=True,
        )

        return validated, errors

    def process_serenicare_form(self, app_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process and validate the full Serenicare form using the controller's validation logic.
        """
        if not self.controller:
            raise Exception("Serenicare controller not initialized")
        return self.controller.update_serenicare_form(app_id, payload)

    # -------------------------------------------------------------------------
    # PREMIUM CALCULATION
    # -------------------------------------------------------------------------
    def _calculate_serenicare_premium(self, data: Dict, plan: Dict) -> Dict:
        """
        Calculate Serenicare premium based on plan tier and optional benefits.

        Returns:
            {
                "monthly": float,
                "annual": float,
                "breakdown": dict
            }
        """
        return premium_service.calculate_sync(
            "serenicare",
            {"data": data, "plan": plan},
        )

    async def complete_flow(self, collected_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """Finalize the flow from already-collected data.

        Convenience helper for tests/integrations that want to skip the step-by-step UI.
        """
        data = dict(collected_data or {})
        data.setdefault("user_id", user_id)
        data.setdefault("product_id", "serenicare")

        result = await self._step_choose_plan_and_pay({"action": "proceed_to_pay"}, data, user_id)
        result.setdefault("status", "success")
        return result

    async def start(self, user_id: str, initial_data: Dict) -> Dict:
        data = dict(initial_data or {})
        data.setdefault("user_id", user_id)
        data.setdefault("product_id", "serenicare")
        if self.controller:
            app = self.controller.create_application(user_id, data)
            data["application_id"] = app.get("id")
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

        if current_step == 0:
            return await self._step_about_you(payload, collected_data, user_id)
        if current_step == 1:
            return await self._step_plan_selection(payload, collected_data, user_id)
        if current_step == 2:
            return await self._step_optional_benefits(payload, collected_data, user_id)
        if current_step == 3:
            return await self._step_medical_conditions(payload, collected_data, user_id)
        if current_step == 4:
            return await self._step_cover_personalization(payload, collected_data, user_id)
        if current_step == 5:
            return await self._step_premium_and_download(payload, collected_data, user_id)
        if current_step == 6:
            return await self._step_choose_plan_and_pay(payload, collected_data, user_id)
        return {"error": "Invalid step"}

    async def _step_cover_personalization(self, payload: Dict, data: Dict, user_id: str) -> Dict:
        errors: Dict[str, str] = {}
        if payload and "_raw" not in payload:
            validated, errors = self._validate_cover_personalization(payload)
            if not errors:
                data["cover_personalization"] = {
                    "date_of_birth": validated.get("date_of_birth", ""),
                    "include_spouse": validated.get("include_spouse", False),
                    "include_children": validated.get("include_children", False),
                    "add_another_main_member": validated.get("add_another_main_member", False),
                    "spouse_dob": validated.get("spouse_dob", ""),
                    "child_dob": validated.get("child_dob", ""),
                    "other_member_dob": validated.get("other_member_dob", ""),
                }
                app_id = data.get("application_id")
                if self.controller and app_id:
                    self.controller.update_cover_personalization(app_id, validated)

        prefilled = data.get("cover_personalization", {})
        fields = [
            {
                "name": "date_of_birth",
                "label": "Date of Birth",
                "type": "date",
                "required": True,
                "defaultValue": prefilled.get("date_of_birth", ""),
            },
            {
                "name": "include_spouse",
                "label": "Include Spouse/Partner",
                "type": "checkbox",
                "required": False,
                "description": "Add your spouse or partner to your cover",
                "defaultValue": prefilled.get("include_spouse", False),
            },
            {
                "name": "spouse_dob",
                "label": "Spouse/Partner Date of Birth",
                "type": "date",
                "required": bool(prefilled.get("include_spouse", False)),
                "description": "Required when spouse/partner is included",
                "defaultValue": prefilled.get("spouse_dob", ""),
            },
            {
                "name": "include_children",
                "label": "Include Child/Children",
                "type": "checkbox",
                "required": False,
                "description": "Add your child or children to your cover",
                "defaultValue": prefilled.get("include_children", False),
            },
            {
                "name": "child_dob",
                "label": "Child Date of Birth",
                "type": "date",
                "required": bool(prefilled.get("include_children", False)),
                "description": "Required when adding child/children",
                "defaultValue": prefilled.get("child_dob", ""),
            },
            {
                "name": "add_another_main_member",
                "label": "Add another main member",
                "type": "checkbox",
                "required": False,
                "defaultValue": prefilled.get("add_another_main_member", False),
            },
            {
                "name": "other_member_dob",
                "label": "Other Main Member Date of Birth",
                "type": "date",
                "required": bool(prefilled.get("add_another_main_member", False)),
                "description": "Required when adding another main member",
                "defaultValue": prefilled.get("other_member_dob", ""),
            },
        ]
        fields_with_validation = [
            {
                **f,
                "backendValidation": True,
                "validateOn": f.get("validateOn", "blur"),
                "blockNextUntilValid": True,
            }
            for f in FieldDecorator.decorate(fields, errors=errors)
        ]

        return {
            "response": {
                "type": "form",
                "message": "👤 Cover Personalization",
                "fields": fields_with_validation,
            },
            "next_step": 4 if errors else 5,
            "collected_data": data,
        }

    async def _step_optional_benefits(self, payload: Dict, data: Dict, user_id: str) -> Dict:
        if payload and "_raw" not in payload:
            selected = payload.get("optional_benefits") or []
            if isinstance(selected, str):
                selected = [s.strip() for s in selected.split(",") if s.strip()]
            data["optional_benefits"] = selected
            app_id = data.get("application_id")
            if self.controller and app_id:
                self.controller.update_optional_benefits(app_id, payload)
        return {
            "response": {
                "type": "checkbox",
                "message": "Select any optional benefits you want to add",
                "options": SERENICARE_OPTIONAL_BENEFITS,
            },
            "next_step": 3,
            "collected_data": data,
        }

    async def _step_medical_conditions(self, payload: Dict, data: Dict, user_id: str) -> Dict:
        if payload and "_raw" not in payload:
            data["medical_conditions"] = {
                "has_condition": payload.get("has_condition", False),
            }
            app_id = data.get("application_id")
            if self.controller and app_id:
                self.controller.update_medical_conditions(app_id, payload)
        return {
            "response": {
                "type": "radio",
                "message": (
                    "Do you or any family members you wish to include have any of the following: "
                    "Sickle Cells, Cancer(s), Leukaemia, or liver-related conditions?"
                ),
                "question_id": "medical_conditions",
                "options": [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}],
                "required": True,
            },
            "next_step": 4,
            "collected_data": data,
        }

    async def _step_plan_selection(self, payload: Dict, data: Dict, user_id: str) -> Dict:
        errors: Dict[str, str] = {}

        if payload and "_raw" not in payload:
            raw_plan = (
                payload.get("plan_option")
                or payload.get("plan_id")
                or payload.get("selected_plan")
                or payload.get("selected_option")
                or payload.get("id")
                or payload.get("value")
            )

            if isinstance(raw_plan, dict):
                plan_id = str(raw_plan.get("id") or raw_plan.get("value") or "").strip()
            else:
                plan_id = str(raw_plan or "").strip()

            if not plan_id:
                action = str(payload.get("action") or "").strip().lower()
                action_to_plan = {p["id"]: p["id"] for p in SERENICARE_PLANS}
                plan_id = action_to_plan.get(action, "")

            if not plan_id:
                errors["plan_option"] = "Plan selection is required"

            plan = next((p for p in SERENICARE_PLANS if p["id"] == plan_id), None)
            if plan and not errors:
                data["plan_option"] = plan
                app_id = data.get("application_id")
                if self.controller and app_id:
                    self.controller.update_plan_selection(app_id, {"plan_option": plan_id})
            elif plan_id and not errors:
                errors["plan_option"] = "Please select a valid plan"

        selected_plan_id = ((data.get("plan_option") or {}).get("id") or "").strip()
        return {
            "response": {
                "type": "options",
                "message": "Choose your Serenicare plan",
                "options": [
                    {
                        "id": p["id"],
                        "label": p["label"],
                        "description": p["description"],
                        "benefits": p["benefits"],
                        "selected": p["id"] == selected_plan_id,
                    }
                    for p in SERENICARE_PLANS
                ],
                "field_errors": errors,
            },
            "next_step": 1 if errors else 2,
            "collected_data": data,
        }

    async def _step_about_you(self, payload: Dict, data: Dict, user_id: str) -> Dict:
        errors: Dict[str, str] = {}
        if payload and "_raw" not in payload:
            validated, errors = self._validate_about_you(payload)
            if not errors:
                data["about_you"] = {
                    "first_name": validated.get("first_name", ""),
                    "middle_name": validated.get("middle_name", ""),
                    "surname": validated.get("surname", ""),
                    "phone_number": payload.get("phone_number", ""),
                    "phone_number_normalized": validated.get("phone_number", ""),
                    "email": validated.get("email", ""),
                }
                app_id = data.get("application_id")
                if self.controller and app_id:
                    self.controller.update_about_you(app_id, payload)

        prefilled = data.get("about_you", {})
        fields = [
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
        fields_with_validation = [
            {
                **f,
                "backendValidation": True,
                "validateOn": f.get("validateOn", "blur"),
                "blockNextUntilValid": True,
            }
            for f in FieldDecorator.decorate(fields, errors=errors)
        ]

        return {
            "response": {
                "type": "form",
                "message": "About You",
                "fields": fields_with_validation,
            },
            "next_step": 0 if errors else 1,
            "collected_data": data,
        }

    async def _step_premium_and_download(self, payload: Dict, data: Dict, user_id: str) -> Dict:
        plan = data.get("plan_option") or SERENICARE_PLANS[0]
        premium = self._calculate_serenicare_premium(data, plan)
        quotation = premium_service.build_quotation_sync(data)
        quote_id = str(quotation.get("quote_number") or "")
        data["integration_premium"] = premium
        data["integration_quotation"] = quotation
        data["integration_quote_id"] = quote_id
        quote_result = generate_and_register_quote_pdf(
            "serenicare",
            data,
            quote_id=quote_id,
            product_name="Serenicare",
        )
        download_url = quote_result["download_url"]
        return {
            "response": {
                "type": "premium_summary",
                "message": "💰 Your Serenicare premium",
                "product_name": "Serenicare",
                "plan": plan["label"],
                "monthly_premium": premium["monthly"],
                "annual_premium": premium["annual"],
                "breakdown": premium.get("breakdown", {}),
                "download_option": True,
                "download_label": "Download summary (PDF)",
                "download_url": download_url,
                "quote_id": quote_id,
                "actions": [
                    {"type": "download_quote", "label": "Download Quote"},
                    {"type": "proceed_to_pay", "label": "Proceed to Pay"},
                ],
            },
            "next_step": 6,
            "collected_data": data,
        }

    async def _step_choose_plan_and_pay(self, payload: Dict, data: Dict, user_id: str) -> Dict:
        action = (payload.get("action") or payload.get("_raw") or "").strip().lower()

        # Handle download quote action
        if "download" in action:
            return {
                "response": {
                    "type": "premium_summary",
                    "message": "Quote downloaded successfully! Ready to proceed to payment?",
                    "download_status": "success",
                    "quote_id": data.get("integration_quote_id") or data.get("quote_id"),
                    "actions": [
                        {"type": "proceed_to_pay", "label": "Proceed to Pay"},
                    ],
                },
                "next_step": 6,
                "collected_data": data,
            }

        premium = data.get("integration_premium")
        quotation = data.get("integration_quotation")
        integration_quote_id = str(data.get("integration_quote_id") or "").strip()

        if not premium or not quotation:
            plan = data.get("plan_option") or SERENICARE_PLANS[0]
            premium = self._calculate_serenicare_premium(data, plan)
            quotation = premium_service.build_quotation_sync(data)
            integration_quote_id = str(quotation.get("quote_number") or "")
            data["integration_premium"] = premium
            data["integration_quotation"] = quotation
            data["integration_quote_id"] = integration_quote_id

        response_quote_id = integration_quote_id
        app_id = data.get("application_id")
        if self.controller and app_id:
            app = self.controller.finalize_and_create_quote(app_id, user_id, premium)
            data["quote_id"] = app.get("quote_id") if app else None
        else:
            quote = self.db.create_quote(
                user_id=user_id,
                product_id=data.get("product_id", "serenicare"),
                premium_amount=premium["monthly"],
                sum_assured=None,
                underwriting_data=data,
                pricing_breakdown=premium.get("breakdown"),
                product_name="Serenicare",
            )
            data["quote_id"] = str(quote.id)

        if not response_quote_id:
            response_quote_id = str(data.get("quote_id") or "")

        return {
            "response": {
                "type": "proceed_to_payment",
                "message": "Proceeding to payment. Choose your payment method.",
                "quote_id": response_quote_id,
            },
            "complete": True,
            "next_flow": "payment",
            "collected_data": data,
            "data": {"quote_id": response_quote_id},
        }
