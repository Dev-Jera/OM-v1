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

from src.utils.llm_provider import (
    is_openrouter_enabled,
    openrouter_api_key,
    openrouter_base_url,
    openrouter_model,
    openrouter_session,
    post_chat_completion,
)
from src.utils.pii_redaction import clean_history, redact_history, redact_text
from src.utils.response_safety import looks_truncated, merge_continuation, strip_meta_lead_in

logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("CONVERSATIONAL_BRAIN_MODEL", "gemini-3.6-flash")

PRODUCT_FLOWS = ("personal_accident", "travel_insurance", "motor_private", "serenicare")

SYSTEM_INSTRUCTION = """
You are MIA, the virtual assistant for Old Mutual Uganda.

INSIDER VOICE:
- Reply like a seasoned Old Mutual product specialist: confident, warm, and knowledgeable.
  State facts plainly as product knowledge.
- NEVER mention or hint at how you get your information. Never use phrases like
  "retrieved information", "available information", "the information available",
  "knowledge base", "search results", "sources", "documents", "according to our
  data/records", "the tool returned", "I couldn't find", "no information", or
  "doesn't specifically detail". Your knowledge is simply your knowledge.
- NEVER open a reply by describing what information is or isn't available. Acknowledge
  the user's question and answer it directly from the first sentence.
- Never hedge with phrases like "the retrieved information doesn't state...". If a
  detail is genuinely not covered, say so naturally like an insider, e.g. "That specific
  detail isn't covered in our published guide - let me connect you with an agent who can
  confirm it." Never expose retrieval mechanics.

CONVERSATION RULES:
- Talk naturally and warmly, like a human. Ask relevant follow-up questions one at a time.
- You ONLY talk about Old Mutual products, services, savings, investments, and insurance.
- If the user is not talking about Old Mutual, politely steer them back. Never chat about unrelated topics.
- If you truly do not know something, say so naturally and offer to connect the user with a
  human agent (without mentioning any tools or search).

KNOWLEDGE GROUNDING:
- ALWAYS call `search_knowledge_base` before answering any question about Old
  Mutual products, coverage, benefits, pricing, claims, or services.
- Any fact about Old Mutual products comes from the `search_knowledge_base` tool.
- NEVER invent facts, figures, benefits, prices, or product details.
- NEVER answer Old Mutual questions from your own general knowledge or memory.
- If the tool returns no useful information, respond as an insider would: share what IS known,
  and for genuinely missing details say they aren't covered in the published guide and offer a
  human agent. Keep this natural - never mention the tool or retrieval in your reply.
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

EXAMPLE - state facts like an insider, not like a search result:
- BAD: "For the Balanced Fund, the retrieved information outlines various contribution
  methods like direct debit, M-Pesa, cheques, or standing orders. However, it doesn't
  explicitly state whether monthly deposits are mandatory."
- GOOD: "You can fund the Balanced Fund by direct debit, M-Pesa, cheque, or standing order -
  whichever suits you. On contribution frequency, our published guide doesn't call out a fixed
  monthly minimum; if you'd like, I can connect you with an agent to confirm the exact setup."
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
                    "services. ALWAYS call this tool BEFORE answering any question about "
                    "Old Mutual products - never answer such a question without its "
                    "results. Returns relevant document excerpts that are the ONLY "
                    "allowed source of facts."
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
                    "Mutual product. Choose the detected product key, or 'unknown' if "
                    "the product cannot be detected."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product": {
                            "type": "string",
                            "enum": ["unknown"] + list(PRODUCT_FLOWS),
                            "description": "The detected product key, or 'unknown' if it cannot be detected.",
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


def _function_call_id(fc: Any) -> Optional[str]:
    try:
        call_id = getattr(fc, "id", None)
        return str(call_id) if call_id else None
    except Exception:
        return None


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
            calls.append({"name": name, "args": _function_call_args(fc), "id": _function_call_id(fc)})
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


def _build_openai_messages(history: List[Dict[str, Any]], message: str) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    for msg in (history or [])[-8:]:
        role = (msg.get("role") or "").strip().lower()
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        role_key = "assistant" if role == "assistant" else "user"
        messages.append({"role": role_key, "content": content[:1200]})
    messages.append({"role": "user", "content": message[:2000]})
    return messages


def _openai_tools() -> List[Dict[str, Any]]:
    """Convert the Gemini function-declaration list into OpenAI tool definitions."""
    tools: List[Dict[str, Any]] = []
    for block in _TOOLS:
        for fd in block.get("function_declarations") or []:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": fd["name"],
                        "description": fd.get("description", ""),
                        "parameters": fd.get("parameters", {"type": "object"}),
                    },
                }
            )
    return tools


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
        self.provider = "gemini"
        self._or_http = None
        self._or_base_url = ""
        self._or_api_key = ""
        self._or_model = ""
        if self.llm is None:
            try:
                if is_openrouter_enabled():
                    if not openrouter_api_key():
                        raise RuntimeError("OPENROUTER_API_KEY is missing; ConversationalBrain disabled.")
                    self.provider = "openrouter"
                    self._or_http = openrouter_session()
                    self._or_base_url = openrouter_base_url()
                    self._or_api_key = openrouter_api_key()
                    self._or_model = openrouter_model()
                else:
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

    @staticmethod
    def _was_truncated(response: Any, text: str) -> bool:
        """True when the LLM reported a token-limit cut-off or the text reads as cut off."""
        try:
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                finish_reason = getattr(candidates[0], "finish_reason", None)
                # Gemini SDK may return an enum or a plain int; MAX_TOKENS = 2.
                finish_reason_val = getattr(finish_reason, "value", finish_reason)
                if finish_reason_val == 2:
                    return True
        except Exception:  # pragma: no cover - depends on SDK shape
            pass
        return looks_truncated(text)

    async def _ensure_complete(
        self, response: Any, contents: List[Dict[str, Any]], config: Any, text: str
    ) -> str:
        """Request one continuation round when the reply was cut off."""
        if not self._was_truncated(response, text):
            return text
        continuation_prompt = (
            "Continue the answer from where it stopped. "
            "Do not repeat the text already provided. "
            "Finish the incomplete thought in 1-3 short sentences.\n\n"
            f"Current partial answer:\n{text}"
        )
        try:
            continuation = await self._call_llm(
                contents + [{"role": "user", "parts": [{"text": continuation_prompt}]}],
                config,
            )
            continuation_text = _response_text(continuation)
            if continuation_text:
                text = merge_continuation(text, continuation_text)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Brain continuation attempt failed: %s", exc)
        return text

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

        if self.provider == "openrouter":
            return await self._converse_openrouter(message, history, pending_quote_offer)

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
                    text = await self._ensure_complete(response, contents, config, text)
                    text = strip_meta_lead_in(text)
                    if not text:
                        logger.warning("Brain returned empty reply after safety checks")
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
                                            "id": call.get("id"),
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
                                            "id": call.get("id"),
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
                                            "id": call.get("id"),
                                            "response": {"error": "unknown tool"},
                                        }
                                    }
                                ],
                            }
                        )

                contents = contents + [_model_content(response)] + function_responses
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

        if self.provider == "openrouter":
            return await self._confirm_quote_openrouter(message, history)

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

    # -- OpenRouter path --------------------------------------------------------

    async def _call_openrouter(
        self,
        *,
        messages: List[Dict[str, Any]],
        system: str,
        temperature: float,
        max_tokens: int,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> dict:
        def _sync() -> dict:
            return post_chat_completion(
                session=self._or_http,
                base_url=self._or_base_url,
                api_key=self._or_api_key,
                model=self._or_model,
                messages=[{"role": "system", "content": system}] + messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
            )

        return await asyncio.to_thread(_sync)

    async def _converse_openrouter(
        self,
        message: str,
        history: Optional[List[Dict[str, Any]]] = None,
        pending_quote_offer: bool = False,
    ) -> Optional[ConversationResult]:
        """OpenAI-format tool loop (used when LLM_PROVIDER=openrouter)."""
        masked_message, _ = redact_text(message)
        if not masked_message.strip():
            return None

        clean = clean_history(history or [])
        masked_history = redact_history(clean)
        messages = _build_openai_messages(masked_history, masked_message)

        system = SYSTEM_INSTRUCTION
        if pending_quote_offer:
            system += (
                "\n\nThe user is responding to your quotation offer. Decide if they want to "
                "proceed, then reply accordingly."
            )
        tools = _openai_tools()

        used_knowledge = False
        sources: List[Dict[str, Any]] = []
        quote_requested = False
        product: Optional[str] = None

        try:
            for _round in range(self.max_tool_rounds + 1):
                response = await self._call_openrouter(
                    messages=messages,
                    system=system,
                    temperature=0.3,
                    max_tokens=1200,
                    tools=tools,
                )
                choice = (response.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                text = str(msg.get("content") or "").strip()
                tool_calls = msg.get("tool_calls") or []

                if not tool_calls:
                    if not text:
                        logger.warning("Brain returned empty reply")
                        return None
                    text = strip_meta_lead_in(text)
                    if not text:
                        logger.warning("Brain returned empty reply after safety checks")
                        return None
                    return ConversationResult(
                        reply=text,
                        used_knowledge=used_knowledge,
                        sources=sources,
                        quote_requested=quote_requested,
                        product=product,
                    )

                messages.append(
                    {"role": "assistant", "content": text or None, "tool_calls": tool_calls}
                )
                for call in tool_calls:
                    name = str((call.get("function") or {}).get("name") or "")
                    try:
                        args = json.loads(str((call.get("function") or {}).get("arguments") or "{}"))
                    except Exception:
                        args = {}
                    call_id = str(call.get("id") or "")
                    if name == "search_knowledge_base":
                        query = str(args.get("query") or "").strip() or masked_message
                        hits = await self._retrieve(query)
                        used_knowledge = True
                        sources.extend(hits)
                        result = _hits_to_results(hits)
                    elif name == "request_guided_quote":
                        quote_requested = True
                        detected = str(args.get("product") or "").strip()
                        product = detected if detected in PRODUCT_FLOWS else None
                        result = {"ok": True, "loaded": True}
                    else:
                        result = {"error": "unknown tool"}
                    messages.append(
                        {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result)}
                    )
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("ConversationalBrain.converse failed: %s", exc, exc_info=True)
            return None

        return None

    async def _confirm_quote_openrouter(
        self, message: str, history: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        masked_message, _ = redact_text(message)
        clean = clean_history(history or [])
        masked_history = redact_history(clean)
        messages = _build_openai_messages(masked_history, masked_message)
        try:
            response = await self._call_openrouter(
                messages=messages,
                system=QUOTE_CONFIRM_INSTRUCTION,
                temperature=0.0,
                max_tokens=40,
                tools=None,
            )
            choice = (response.get("choices") or [{}])[0]
            text = str((choice.get("message") or {}).get("content") or "").strip()
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
        cfg: Dict[str, Any] = {
            "system_instruction": system,
            "temperature": 0.3,
            "max_output_tokens": 1200,
            "tools": _TOOLS,
        }
        # The brain runs its own function-call loop, so disable the SDK's
        # built-in Automatic Function Calling (AFC). Otherwise it can interfere
        # with the manual tool loop (and emits noisy "AFC is enabled" logs).
        try:
            from google.genai import types

            if hasattr(types, "AutomaticFunctionCallingConfig"):
                # maximum_remote_calls=0 prevents the SDK warning when AFC is
                # disabled while its default remote-call limit is still set.
                cfg["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
                    disable=True, maximum_remote_calls=0
                )
        except Exception:  # pragma: no cover - depends on SDK version
            pass
        return cfg

    def _confirmation_config(self) -> Any:
        return {
            "system_instruction": QUOTE_CONFIRM_INSTRUCTION,
            "response_mime_type": "application/json",
            "temperature": 0.0,
            "max_output_tokens": 40,
        }


def _model_content(response: Any) -> Any:
    """Return the model's original content object for the next tool round.

    Returning the SDK object (not a rebuilt dict) preserves fields the API
    requires on continuation - notably the ``thought_signature`` that newer
    Gemini models attach to function-call parts. Stripping it triggers a
    400 INVALID_ARGUMENT on the next tool round.
    """
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        raise RuntimeError("Brain response has no candidates")
    content = getattr(candidates[0], "content", None)
    if content is None:
        raise RuntimeError("Brain response candidate has no content")
    return content
