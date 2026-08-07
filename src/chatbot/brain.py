"""
Conversational brain - a single LLM-driven understanding + answering layer.

Every free-text chat message goes to the brain (Gemini via function calling).
The brain decides on its own:

- whether it needs facts from the knowledge base (``search_knowledge_base``),
- whether the user wants a quotation (``request_guided_quote``),
- how to reply naturally in any phrasing, language, or with typos.

Grounding rule: any Old Mutual fact must come from the knowledge base tool.
The brain never answers product questions from its own general knowledge.

Privacy rule: the message and conversation history are PII-redacted before
they are ever sent to the LLM, and form payloads are never included.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.utils.pii_redaction import clean_history, redact_history, redact_text

logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("CONVERSATIONAL_BRAIN_MODEL", "gemini-2.5-flash")

PRODUCT_FLOWS = ("personal_accident", "travel_insurance", "motor_private", "serenicare")

SYSTEM_INSTRUCTION = """
You are MIA, the virtual assistant for Old Mutual Uganda.

CONVERSATION RULES:
- Talk naturally and warmly, like a human. Ask relevant follow-up questions one at a time.
- You ONLY talk about Old Mutual products, services, savings, investments, and insurance.
- If the user is not talking about Old Mutual, politely steer them back. Never chat about unrelated topics.
- If you do not know something, say so and offer to connect the user with a human agent.

KNOWLEDGE GROUNDING:
- Any fact about Old Mutual products must come from the `search_knowledge_base` tool.
- NEVER invent facts, figures, benefits, prices, or product details.
- NEVER answer Old Mutual questions from your own general knowledge or memory.
- If the tool returns no useful information, say you don't have that detail and offer a human agent.
- Paraphrase naturally; do not repeat section headings or copy text verbatim from the sources.

PRIVACY:
- Never ask users for personal details (name, phone number, ID, passport, address) in chat.
- If the user shares personal details, do NOT repeat them, do NOT store them, and gently note
  they can enter them in the secure form when applying.
- Never include personal details in your reply.

QUOTATIONS:
- When the user wants a quotation, an application, or to buy a product, call `request_guided_quote`
  with the detected product key, then invite them to click the button to load the form.
- Never collect quote form details (names, phones, ID numbers) yourself.

FORMAT:
- Keep replies conversational and reasonably short (a few sentences; bullet lists are fine).
- Use **bold** for product names.
""".strip()

QUOTE_CONFIRM_INSTRUCTION = """
The assistant previously offered to load a quotation form and asked the user whether they want to proceed.
Read the user's latest message and decide their intent.

Return JSON ONLY, e.g.:
- {"decision": "proceed"} if they agree or confirm (yes, sure, go ahead, ok, please, proceed).
- {"decision": "cancel"} if they decline (no, not now, later, cancel, nevermind).
- {"decision": "other"} if their message is unrelated to the quote offer.
""".strip()

_TOOLS: List[Dict[str, Any]] = [
    {
        "function_declarations": [
            {
                "name": "search_knowledge_base",
                "description": (
                    "Search the Old Mutual knowledge base for facts about products, "
                    "coverage, benefits, eligibility, exclusions, pricing, claims, and "
                    "services. Use this for ANY Old Mutual factual question. Returns "
                    "relevant document excerpts that are the ONLY allowed source of facts."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "A focused search query describing the facts needed.",
                        }
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "request_guided_quote",
                "description": (
                    "Call this when the user wants a quotation, to apply, or to buy an Old "
                    "Mutual product. Choose the detected product key, or empty string if "
                    "the product is unknown."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product": {
                            "type": "string",
                            "enum": [""] + list(PRODUCT_FLOWS),
                            "description": "The detected product key, or empty string if unknown.",
                        }
                    },
                    "required": ["product"],
                },
            },
        ]
    }
]


@dataclass
class ConversationResult:
    reply: str = ""
    confidence: float = 0.5
    used_knowledge: bool = False
    sources: List[Dict[str, Any]] = field(default_factory=list)
    quote_requested: bool = False
    product: Optional[str] = None
    confirm_quote: Optional[str] = None  # "proceed" | "cancel" | "other"


def _env_bool(name: str, default: bool = True) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _response_text(response: Any) -> str:
    try:
        text = getattr(response, "text", None)
    except Exception:
        return ""
    return (text or "").strip() if isinstance(text, str) else ""


def _function_calls(response: Any) -> List[Dict[str, Any]]:
    """Extract (name, args) pairs from a Gemini response's function calls."""
    calls: List[Dict[str, Any]] = []
    try:
        candidates = getattr(response, "candidates", None) or []
    except Exception:
        return calls
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        parts = getattr(content, "parts", None) or []
        for part in parts:
            fc = getattr(part, "function_call", None)
            if fc is None:
                continue
            name = str(getattr(fc, "name", "") or "")
            if not name:
                continue
            calls.append({"name": name, "args": _function_call_args(fc)})
    return calls


def _function_call_args(fc: Any) -> Dict[str, Any]:
    args = getattr(fc, "args", None)
    if not args:
        return {}
    if isinstance(args, dict):
        return args
    try:
        return {k: v for k, v in dict(args).items()}
    except Exception:
        pass
    try:
        from google.genai import types

        raw = types.FunctionCall.to_json(fc)
        parsed = json.loads(raw)
        inner = parsed.get("args") or parsed.get("argsJson") or {}
        return inner if isinstance(inner, dict) else {}
    except Exception:
        return {}


def _coalesce(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge consecutive messages with the same role (Gemini requires alternation)."""
    out: List[Dict[str, Any]] = []
    for part in parts:
        if out and out[-1]["role"] == part["role"]:
            out[-1]["parts"][0]["text"] += "\n\n" + part["parts"][0]["text"]
        else:
            out.append(part)
    return out


def _build_contents(history: List[Dict[str, Any]], message: str) -> List[Dict[str, Any]]:
    parts: List[Dict[str, Any]] = []
    for msg in (history or [])[-8:]:
        role = (msg.get("role") or "").strip().lower()
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        role_key = "assistant" if role == "assistant" else "user"
        parts.append({"role": role_key, "parts": [{"text": content[:1200]}]})
    parts.append({"role": "user", "parts": [{"text": message[:2000]}]})
    return _coalesce(parts)


def _hits_to_results(hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not hits:
        return {"results": []}
    out: List[Dict[str, Any]] = []
    for h in hits[:5]:
        payload = h.get("payload") or {}
        text = str(payload.get("text") or "").strip()
        if not text:
            continue
        out.append(
            {
                "title": payload.get("title") or payload.get("doc_id") or "Old Mutual document",
                "text": text,
            }
        )
    return {"results": out}


class ConversationalBrain:
    """
    Single LLM brain for free-form chat.

    ``llm`` (optional async callable ``(contents, config) -> response``) allows
    tests to inject a fake. ``retrieve_fn`` (optional async callable
    ``(query, filters) -> hits``) defaults to ``None`` (no retrieval available).
    """

    def __init__(
        self,
        *,
        model_name: str = MODEL_NAME,
        llm: Optional[Callable[[List[Dict[str, Any]], Any], Any]] = None,
        retrieve_fn: Optional[Callable[..., Any]] = None,
        enabled: Optional[bool] = None,
        max_tool_rounds: int = 2,
        api_key_env: str = "GEMINI_API_KEY",
    ) -> None:
        self.model_name = model_name
        self.llm = llm
        self.retrieve_fn = retrieve_fn
        self.max_tool_rounds = max_tool_rounds
        self.enabled = _env_bool("CONVERSATIONAL_BRAIN_ENABLED") if enabled is None else enabled

        self.client = None
        if self.llm is None:
            try:
                from google import genai

                api_key = os.environ.get(api_key_env)
                if not api_key:
                    raise RuntimeError(f"{api_key_env} is missing; ConversationalBrain disabled.")
                self.client = genai.Client(api_key=api_key)
            except Exception as exc:  # pragma: no cover - depends on env
                logger.warning("ConversationalBrain unavailable: %s", exc)
                self.enabled = False

    # -- internal plumbing ---------------------------------------------------

    async def _call_llm(self, contents: List[Dict[str, Any]], config: Any) -> Any:
        if self.llm is not None:
            return await self.llm(contents, config)
        if self.client is None:
            raise RuntimeError("ConversationalBrain has no LLM client")
        from google.genai import types

        def _sync() -> Any:
            return self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(**config) if isinstance(config, dict) else config,
            )

        return await asyncio.to_thread(_sync)

    async def _retrieve(self, query: str) -> List[Dict[str, Any]]:
        if self.retrieve_fn is None:
            return []
        try:
            return await self.retrieve_fn(query=query, filters=None) or []
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Knowledge base retrieval failed: %s", exc)
            return []

    # -- public API -----------------------------------------------------------

    async def converse(
        self,
        message: str,
        history: Optional[List[Dict[str, Any]]] = None,
        topic: Optional[Dict[str, Any]] = None,
        pending_quote_offer: bool = False,
    ) -> Optional[ConversationResult]:
        """Run one conversation turn with the brain. Returns None if unusable."""
        if not self.enabled:
            return None

        masked_message, _ = redact_text(message)
        if not masked_message.strip():
            return None

        clean = clean_history(history or [])
        masked_history = redact_history(clean)

        contents = _build_contents(masked_history, masked_message)
        config = self._conversation_config(pending_quote_offer=pending_quote_offer)

        used_knowledge = False
        sources: List[Dict[str, Any]] = []
        quote_requested = False
        product: Optional[str] = None

        try:
            for _round in range(self.max_tool_rounds + 1):
                response = await self._call_llm(contents, config)
                calls = _function_calls(response)

                if not calls:
                    text = _response_text(response)
                    if not text:
                        logger.warning("Brain returned empty reply")
                        return None
                    return ConversationResult(
                        reply=text,
                        used_knowledge=used_knowledge,
                        sources=sources,
                        quote_requested=quote_requested,
                        product=product,
                    )

                function_responses: List[Dict[str, Any]] = []
                for call in calls:
                    name = call["name"]
                    args = call["args"]
                    if name == "search_knowledge_base":
                        query = str(args.get("query") or "").strip() or masked_message
                        hits = await self._retrieve(query)
                        used_knowledge = True
                        sources.extend(hits)
                        function_responses.append(
                            {
                                "role": "user",
                                "parts": [
                                    {
                                        "function_response": {
                                            "name": name,
                                            "response": _hits_to_results(hits),
                                        }
                                    }
                                ],
                            }
                        )
                    elif name == "request_guided_quote":
                        quote_requested = True
                        detected = str(args.get("product") or "").strip()
                        product = detected if detected in PRODUCT_FLOWS else None
                        function_responses.append(
                            {
                                "role": "user",
                                "parts": [
                                    {
                                        "function_response": {
                                            "name": name,
                                            "response": {"ok": True, "loaded": True},
                                        }
                                    }
                                ],
                            }
                        )
                    else:
                        function_responses.append(
                            {
                                "role": "user",
                                "parts": [
                                    {
                                        "function_response": {
                                            "name": name,
                                            "response": {"error": "unknown tool"},
                                        }
                                    }
                                ],
                            }
                        )

                contents = contents + [response_content(response)] + function_responses
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("ConversationalBrain.converse failed: %s", exc, exc_info=True)
            return None

        return None

    async def confirm_quote_offer(self, message: str, history: Optional[List[Dict[str, Any]]] = None) -> str:
        """
        Decide the user's reply to a quote-offer confirmation.

        Returns one of: "proceed", "cancel", "other". Falls back to "other"
        on any failure so the conversation simply continues.
        """
        if not self.enabled:
            return "other"

        masked_message, _ = redact_text(message)
        clean = clean_history(history or [])
        masked_history = redact_history(clean)
        contents = _build_contents(masked_history, masked_message)
        config = self._confirmation_config()

        try:
            response = await self._call_llm(contents, config)
            text = _response_text(response)
            if not text:
                return "other"
            parsed = json.loads(text)
            decision = str(parsed.get("decision") or "").strip().lower()
            return decision if decision in ("proceed", "cancel", "other") else "other"
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("confirm_quote_offer failed, defaulting to 'other': %s", exc)
            return "other"

    # -- config helpers --------------------------------------------------------

    def _conversation_config(self, *, pending_quote_offer: bool) -> Any:
        system = SYSTEM_INSTRUCTION
        if pending_quote_offer:
            system += (
                "\n\nThe user is responding to your quotation offer. Decide if they want to "
                "proceed, then reply accordingly."
            )
        return {
            "system_instruction": system,
            "temperature": 0.3,
            "max_output_tokens": 1200,
            "tools": _TOOLS,
        }

    def _confirmation_config(self) -> Any:
        return {
            "system_instruction": QUOTE_CONFIRM_INSTRUCTION,
            "response_mime_type": "application/json",
            "temperature": 0.0,
            "max_output_tokens": 40,
        }


def response_content(response: Any) -> Dict[str, Any]:
    """Extract the assistant content (with its function calls) for continuation."""
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        raise RuntimeError("Brain response has no candidates")
    content = getattr(candidates[0], "content", None)
    if content is None:
        raise RuntimeError("Brain response candidate has no content")
    parts = getattr(content, "parts", None) or []
    role = "model" if getattr(content, "role", None) in (None, "model") else str(content.role)
    return {"role": role, "parts": [{"text": str(p.text)} if getattr(p, "text", None) else {"function_call": _part_function_call(p)} for p in parts]}


def _part_function_call(part: Any) -> Dict[str, Any]:
    fc = getattr(part, "function_call", None)
    if fc is None:
        return {}
    return {
        "name": getattr(fc, "name", None),
        "args": _function_call_args(fc),
    }
