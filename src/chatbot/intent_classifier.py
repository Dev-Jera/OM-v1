import asyncio
import json
import logging
import os
import re
from types import SimpleNamespace
from typing import Optional, Tuple

from google import genai
from google.genai import types

from src.utils.llm_provider import (
    is_openrouter_enabled,
    openrouter_api_key,
    openrouter_base_url,
    openrouter_model,
    openrouter_session,
    post_chat_completion,
)

logger = logging.getLogger(__name__)

# Use the same family as the main generator for consistency.
# Override at runtime with the INTENT_MODEL env var.
INTENT_MODEL_NAME = os.getenv("INTENT_MODEL", "gemini-3.6-flash")

_ROUTER_SYSTEM = """
You are a routing classifier for MIA, the Old Mutual Uganda virtual assistant.

Decide the user's intent and, ONLY for non-product intents, compose a short reply.
Return JSON ONLY, exactly one object:
{"intent": "<LABEL>", "reply": "<text or empty string>"}

Labels:
- OM_QUESTION: the user is asking about an Old Mutual product, service, savings,
  investment, insurance, coverage, benefits, pricing, claims, payments, or anything
  related to Old Mutual Uganda. For this label the "reply" MUST be exactly "".
- QUOTE: the user wants a quotation, to apply, to buy, or to start an application
  for an Old Mutual product. For this label the "reply" MUST be exactly "".
- GREETING, SMALL_TALK, THANKS, GOODBYE: casual chat, a hello/hi in ANY wording
  (e.g. "yo", "yooo", "wasap", "howzit", "sup", "hi there"), gratitude, or farewell.
  Compose a warm, short reply as MIA and put it in "reply".
- OFF_TOPIC: anything unrelated to Old Mutual and not casual chat (weather, news,
  sports, etc.). Compose a short reply steering the user back to Old Mutual.

Rules:
- The "reply" field is ONLY allowed for GREETING, SMALL_TALK, THANKS, GOODBYE, OFF_TOPIC.
- For OM_QUESTION or QUOTE the "reply" field must be exactly "".
- Keep replies to 1-2 short lines. Never give product facts, prices, or financial advice.
""".strip()


class SmallTalkResponder:
    """
    Uses the LLM to generate short, polite replies for NO_RETRIEVAL intents
    (greetings, thanks, small talk, goodbyes) without touching RAG.
    """

    def __init__(self, api_key_env: str = "GEMINI_API_KEY"):
        self.provider = "gemini"
        self._or_http = None
        self._or_base_url = ""
        self._or_api_key = ""
        self._or_model = ""
        if is_openrouter_enabled():
            if not openrouter_api_key():
                raise RuntimeError("OPENROUTER_API_KEY is missing; SmallTalkResponder cannot be used.")
            self.provider = "openrouter"
            self._or_http = openrouter_session()
            self._or_base_url = openrouter_base_url()
            self._or_api_key = openrouter_api_key()
            self._or_model = openrouter_model()
        else:
            api_key = os.environ.get(api_key_env)
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY is missing; SmallTalkResponder cannot be used.")
            self.client = genai.Client(api_key=api_key)

    async def respond(self, message: str, label: str) -> str:
        msg = (message or "").strip()
        label_upper = (label or "").upper()

        system_instruction = """
You are MIA, the Old Mutual Uganda virtual assistant, answering ONLY greetings,
thanks, small talk, and goodbyes.

Rules:
- Reply in 1–2 short lines.
- Be warm and professional.
- Do NOT mention specific product names, benefits, prices, or policy details.
- Do NOT give financial advice.
- Gently invite the user to ask about Old Mutual products or services.
""".strip()

        prompt = f'User message: "{msg}"\n\nIntent label: {label_upper}\n\nReply conversationally for this small-talk intent.'

        try:
            # Use asyncio.to_thread to avoid blocking the event loop
            def _sync_generate():
                if self.provider == "openrouter":
                    result = post_chat_completion(
                        session=self._or_http,
                        base_url=self._or_base_url,
                        api_key=self._or_api_key,
                        model=self._or_model,
                        messages=[
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.3,
                        max_tokens=120,
                    )
                    choices = result.get("choices") or []
                    content = ""
                    if choices:
                        content = (choices[0].get("message") or {}).get("content") or ""
                    return SimpleNamespace(text=content)
                response = self.client.models.generate_content(
                    model=INTENT_MODEL_NAME,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.3,
                        max_output_tokens=120,
                    ),
                )
                return response

            response = await asyncio.to_thread(_sync_generate)
            text = (getattr(response, "text", "") or "").strip()
            if not text:
                return "Hi, I’m MIA. How can I help you with Old Mutual products or services today?"
            return text
        except Exception as e:
            logger.warning("SmallTalkResponder error: %s", e, exc_info=True)
            return "Hi, I’m MIA. How can I help you with Old Mutual products or services today?"


class IntentRouter:
    """LLM-first intent routing.

    :meth:`route` returns a ``(label, reply)`` tuple:

    * ``GREETING / SMALL_TALK / THANKS / GOODBYE / OFF_TOPIC`` with a composed
      reply (or ``None`` for a fast-path match, meaning the caller should use a
      canned reply).
    * ``OM_QUESTION / QUOTE`` with ``reply=None``, meaning the caller must run
      retrieval (and, for ``OM_QUESTION``, is expected to answer only from chunks).
    * ``UNKNOWN`` when the LLM could not be used, so the caller falls through to
      the normal brain / RAG pipeline.
    """

    LABELS = (
        "GREETING",
        "SMALL_TALK",
        "THANKS",
        "GOODBYE",
        "OFF_TOPIC",
        "OM_QUESTION",
        "QUOTE",
        "UNKNOWN",
    )

    def __init__(self, api_key_env: str = "GEMINI_API_KEY", client=None, model: Optional[str] = None):
        self.client = client
        self.provider = "gemini"
        self._or_http = None
        self._or_base_url = ""
        self._or_api_key = ""
        if self.client is None:
            try:
                if is_openrouter_enabled():
                    if not openrouter_api_key():
                        raise RuntimeError("OPENROUTER_API_KEY is missing; IntentRouter disabled.")
                    self.provider = "openrouter"
                    self._or_http = openrouter_session()
                    self._or_base_url = openrouter_base_url()
                    self._or_api_key = openrouter_api_key()
                else:
                    api_key = os.environ.get(api_key_env)
                    if not api_key:
                        raise RuntimeError(f"{api_key_env} is missing; IntentRouter disabled.")
                    self.client = genai.Client(api_key=api_key)
            except Exception as exc:  # pragma: no cover - depends on env
                logger.warning("IntentRouter unavailable: %s", exc)
                self.client = None
        self.model = openrouter_model() if self.provider == "openrouter" else (model or INTENT_MODEL_NAME)

    async def route(self, message: str) -> Tuple[str, Optional[str]]:
        if self.provider == "openrouter":
            if not self._or_api_key:
                return ("UNKNOWN", None)
        elif self.client is None:
            return ("UNKNOWN", None)
        return await self._llm_route((message or "").strip())

    async def _llm_route(self, msg: str) -> Tuple[str, Optional[str]]:
        prompt = f'User message: "{msg}"'
        try:
            response = await asyncio.to_thread(self._sync_generate, _ROUTER_SYSTEM, prompt)
            text = (getattr(response, "text", "") or "").strip()
            return self._parse(text)
        except Exception as exc:
            logger.warning("IntentRouter error: %s", exc, exc_info=True)
            return ("UNKNOWN", None)

    def _sync_generate(self, system_instruction: str, prompt: str):
        if self.provider == "openrouter":
            result = post_chat_completion(
                session=self._or_http,
                base_url=self._or_base_url,
                api_key=self._or_api_key,
                model=self.model,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=200,
            )
            choices = result.get("choices") or []
            content = ""
            if choices:
                content = (choices[0].get("message") or {}).get("content") or ""
            return SimpleNamespace(text=content)
        return self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.0,
                max_output_tokens=200,
            ),
        )

    @staticmethod
    def _parse(text: str) -> Tuple[str, Optional[str]]:
        if not text:
            return ("UNKNOWN", None)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return ("UNKNOWN", None)
        try:
            data = json.loads(match.group(0))
        except Exception:
            return ("UNKNOWN", None)
        label = str(data.get("intent") or "").upper().strip()
        reply = (data.get("reply") or "").strip() or None
        if label not in IntentRouter.LABELS:
            return ("UNKNOWN", None)
        if label in ("OM_QUESTION", "QUOTE"):
            return (label, None)
        return (label, reply)
