"""Dynamic question engine for product-specific guided journeys only.

The engine delegates to the existing product flows, intercepts premium or quote
presentation, and exposes a clean buy intent handoff for the frontend.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .motor_private import MotorPrivateFlow
from .personal_accident import PersonalAccidentFlow
from .serenicare import SerenicareFlow
from .travel_insurance import TravelInsuranceFlow


_PRODUCT_OPTIONS = [
    {"id": "personal_accident", "label": "Personal Accident", "category": "personal"},
    {"id": "serenicare", "label": "Serenicare (Health)", "category": "personal"},
    {"id": "motor_private", "label": "Motor Private", "category": "vehicle"},
    {"id": "travel_insurance", "label": "Travel Insurance", "category": "personal"},
]


def _normalize_choice(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip().lower()
    return str(value).strip().lower()


def _pick_product_from_text(text: str) -> Optional[str]:
    normalized = (text or "").lower()
    if re.search(r"\b(pa|personal accident|accident cover)\b", normalized):
        return "personal_accident"
    if re.search(r"\b(serenicare|health insurance|medical cover|medical insurance)\b", normalized):
        return "serenicare"
    if re.search(r"\b(motor private|car insurance|vehicle insurance|motor insurance)\b", normalized):
        return "motor_private"
    if re.search(r"\b(travel insurance|travel cover|travel sure)\b", normalized):
        return "travel_insurance"
    return None


def _extract_action(user_input: Any) -> str:
    if isinstance(user_input, dict):
        return _normalize_choice(user_input.get("action") or user_input.get("_action") or user_input.get("type"))
    return _normalize_choice(user_input)


def _remove_action(actions: Any, action_type: str) -> Any:
    if not isinstance(actions, list):
        return actions
    return [action for action in actions if not (isinstance(action, dict) and action.get("type") == action_type)]


class DynamicQuestionEngineFlow:
    """Route guided interactions into product-owned journeys only."""

    def __init__(self, product_catalog, db):
        self.catalog = product_catalog
        self.db = db
        self._product_flows = {
            "personal_accident": PersonalAccidentFlow(product_catalog, db),
            "serenicare": SerenicareFlow(product_catalog, db),
            "motor_private": MotorPrivateFlow(product_catalog, db),
            "travel_insurance": TravelInsuranceFlow(product_catalog, db),
        }

    async def start(self, user_id: str, initial_data: Dict) -> Dict:
        collected: Dict[str, Any] = {"engine": {}}
        hinted = (initial_data or {}).get("product_flow") or (initial_data or {}).get("flow")
        if hinted:
            collected["engine"]["product_flow"] = hinted
            collected["engine"]["phase"] = "subflow"
            collected["engine"]["sub_step"] = 0
            collected["engine"]["sub_data"] = dict((initial_data or {}).get("prefill") or {})
            return await self._start_subflow(user_id, collected)

        return {
            "response": {
                "type": "options",
                "message": "What product would you like to understand and get a quote for?",
                "options": [{"id": product["id"], "label": product["label"]} for product in _PRODUCT_OPTIONS],
            },
            "next_step": 0,
            "collected_data": collected,
        }

    async def process_step(self, user_input: Any, current_step: int, collected_data: Dict, user_id: str) -> Dict:
        data = dict(collected_data or {})
        engine: Dict[str, Any] = data.setdefault("engine", {})
        phase = engine.get("phase") or "select_product"

        if phase == "select_product":
            chosen = None
            if isinstance(user_input, dict) and "id" in user_input:
                chosen = user_input.get("id")
            elif isinstance(user_input, str) and user_input.strip():
                chosen = _pick_product_from_text(user_input) or user_input.strip()
            else:
                chosen = _pick_product_from_text(_normalize_choice(user_input))

            chosen = _normalize_choice(chosen)
            valid = {product["id"] for product in _PRODUCT_OPTIONS}
            if chosen not in valid:
                match = None
                if hasattr(self.catalog, "match_products"):
                    hits = self.catalog.match_products(str(user_input or ""), top_k=1)
                    match = hits[0][2] if hits else None

                if match:
                    name = match.get("name") or "this product"
                    url = match.get("url")
                    message = (
                        f"{name} is currently not available as a digital buy-online journey in this chatbot. "
                        "Please visit an Old Mutual branch or contact customer support."
                    )
                    if url:
                        message += f"\n\nMore details: {url}"
                    message += "\n\nDigital products available in-chat: Personal Accident, Serenicare, Motor Private, Travel Insurance."
                    return {
                        "response": {"type": "info", "message": message},
                        "complete": True,
                        "collected_data": data,
                    }

                return {
                    "response": {
                        "type": "options",
                        "message": "Please pick one of these products:",
                        "options": [{"id": product["id"], "label": product["label"]} for product in _PRODUCT_OPTIONS],
                    },
                    "next_step": 0,
                    "collected_data": data,
                }

            engine["product_flow"] = chosen
            engine["phase"] = "subflow"
            engine["sub_step"] = 0
            engine["sub_data"] = engine.get("sub_data") or {}
            engine.pop("awaiting_buy", None)
            return await self._start_subflow(user_id, data)

        if phase == "subflow":
            return await self._continue_subflow(user_id, user_input, data)

        engine.clear()
        return await self.start(user_id, {})

    async def _start_subflow(self, user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        engine = data["engine"]
        flow_id = _normalize_choice(engine.get("product_flow"))
        subflow = self._product_flows.get(flow_id)
        if not subflow:
            engine.clear()
            return await self.start(user_id, {})

        result = await subflow.start(user_id, engine.get("sub_data") or {})
        engine["sub_step"] = 0
        engine["sub_data"] = result.get("collected_data", engine.get("sub_data") or {})
        return {"response": result.get("response"), "next_step": 0, "collected_data": data}

    async def _continue_subflow(self, user_id: str, user_input: Any, data: Dict[str, Any]) -> Dict:
        engine = data["engine"]
        flow_id = _normalize_choice(engine.get("product_flow"))

        if engine.get("awaiting_buy"):
            action = _extract_action(user_input)
            if action in {"buy", "buy_now", "yes", "accept"}:
                return await self._finalize_buy(user_id, data)
            if action in {"not_now", "no", "decline"}:
                return {
                    "response": {"type": "message", "message": "No problem, you can come back anytime to continue."},
                    "complete": True,
                    "collected_data": data,
                }
            engine["awaiting_buy"] = False

        subflow = self._product_flows.get(flow_id)
        if not subflow:
            engine.clear()
            return await self.start(user_id, {})

        step = int(engine.get("sub_step", 0) or 0)
        sub_data = engine.get("sub_data") or {}
        result = await subflow.process_step(user_input=user_input, current_step=step, collected_data=sub_data, user_id=user_id)

        if result.get("collected_data") is not None:
            engine["sub_data"] = result["collected_data"]
        if result.get("next_step") is not None:
            engine["sub_step"] = result["next_step"]

        response = result.get("response") or {}
        if isinstance(response, dict) and response.get("type") in {"premium_summary", "quote_presentation"}:
            response = dict(response)
            response["message"] = response.get("message") or "Here is your quote."
            actions = list(response.get("actions") or [])
            actions = _remove_action(actions, "proceed_to_pay")
            actions = _remove_action(actions, "proceed_to_payment")
            actions = list(actions)
            actions.append({"type": "buy_now", "label": "Buy now"})
            actions.append({"type": "not_now", "label": "Not now"})
            response["actions"] = actions
            response["buy_service"] = "separate"
            engine["awaiting_buy"] = True
            return {"response": response, "next_step": 0, "collected_data": data}

        if result.get("complete") and result.get("data") and result.get("data", {}).get("quote_id"):
            engine["awaiting_buy"] = True
            return {
                "response": {
                    "type": "buy_cta",
                    "message": "Quote ready. Click Buy to continue.",
                    "quote_id": result["data"]["quote_id"],
                    "actions": [{"type": "buy_now", "label": "Buy now"}, {"type": "not_now", "label": "Not now"}],
                    "buy_service": "separate",
                },
                "next_step": 0,
                "collected_data": data,
            }

        return {"response": response, "next_step": 0, "collected_data": data}

    async def _finalize_buy(self, user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        engine = data["engine"]
        flow_id = _normalize_choice(engine.get("product_flow"))
        subflow = self._product_flows.get(flow_id)
        if not subflow:
            engine.clear()
            return await self.start(user_id, {})

        result = await subflow.complete_flow(engine.get("sub_data") or {}, user_id)
        quote_id = None
        if isinstance(result.get("data"), dict):
            quote_id = result["data"].get("quote_id")
        if not quote_id and isinstance(result.get("response"), dict):
            quote_id = result["response"].get("quote_id")

        return {
            "response": {
                "type": "buy_cta",
                "message": "Ready to buy. Click Buy in the frontend to proceed.",
                "quote_id": quote_id,
                "buy_service": "separate",
            },
            "complete": True,
            "collected_data": data,
            "data": {"quote_id": quote_id},
        }
