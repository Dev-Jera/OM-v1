"""LLM-based product selection for the chatbot.

Decides which single Old Mutual product a user message is about, using the
same provider switch (``LLM_PROVIDER``: gemini or openrouter) as the rest of
the bot. This replaces brittle word-matching as the primary picker so phrases
like "how much is a car insurance" resolve to "Motor Insurance" instead of a
token-matched wrong product.

Design rules (mirrors :mod:`src.chatbot.intent_classifier`):
- temperature 0, tiny output; the returned name is validated against the
  provided catalog so the model cannot invent products.
- Any error or ambiguous result returns ``None`` so callers can fall back to
  the legacy :class:`ProductMatcher`.
- Provider follows ``LLM_PROVIDER`` exactly as the rest of the app.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from types import SimpleNamespace
from typing import Optional

logger = logging.getLogger(__name__)

PRODUCT_MODEL_NAME = os.getenv("PRODUCT_MODEL", "gemini-3.6-flash")


class ProductPick:
    """Result of product recognition.

    Attributes:
        name: The product name. Exact catalog product when ``in_catalog`` is
            True; otherwise a raw paraphrase of what the user asked for (which
            may be something we do NOT sell). ``None`` when nothing was captured.
        in_catalog: True when ``name`` is a product Old Mutual actually sells
            (exact match against the catalog). False for non-catalog offers or
            when ``name`` is None.
    """

    __slots__ = ("name", "in_catalog")

    def __init__(self, name: Optional[str], in_catalog: bool):
        self.name = name
        self.in_catalog = bool(in_catalog)

    def __bool__(self):
        return bool(self.name)

    def __repr__(self):  # pragma: no cover - debug aid
        return f"ProductPick(name={self.name!r}, in_catalog={self.in_catalog!r})"


NO_PRODUCT = ProductPick(None, False)


def _provider_hint():
    """Returns a small-import bundle of provider helpers, or None on failure."""
    try:
        from src.utils.llm_provider import (
            is_openrouter_enabled,
            openrouter_api_key,
            openrouter_base_url,
            openrouter_model,
            openrouter_session,
            post_chat_completion,
        )

        return {
            "is_openrouter_enabled": is_openrouter_enabled,
            "openrouter_api_key": openrouter_api_key,
            "openrouter_base_url": openrouter_base_url,
            "openrouter_model": openrouter_model,
            "openrouter_session": openrouter_session,
            "post_chat_completion": post_chat_completion,
        }
    except Exception:  # pragma: no cover - defensive
        return None


class ProductClassifier:
    """Pick the product a user message refers to, using the active LLM provider."""

    def __init__(self, api_key_env: str = "GEMINI_API_KEY", client=None, model: Optional[str] = None):
        self.client = client
        self.provider = "gemini"
        self._or_http = None
        self._or_base_url = ""
        self._or_api_key = ""
        self._helpers = _provider_hint()

        if self.client is None and self._helpers is not None:
            try:
                if self._helpers["is_openrouter_enabled"]():
                    key = self._helpers["openrouter_api_key"]()
                    if not key:
                        raise RuntimeError("OPENROUTER_API_KEY is missing; ProductClassifier disabled.")
                    self.provider = "openrouter"
                    self._or_http = self._helpers["openrouter_session"]()
                    self._or_base_url = self._helpers["openrouter_base_url"]()
                    self._or_api_key = key
                else:
                    from google import genai

                    api_key = os.environ.get(api_key_env)
                    if not api_key:
                        raise RuntimeError(f"{api_key_env} is missing; ProductClassifier disabled.")
                    self.client = genai.Client(api_key=api_key)
            except Exception as exc:  # pragma: no cover - depends on env
                logger.warning("ProductClassifier unavailable: %s", exc)
                self.client = None
        self.model = (
            self._helpers["openrouter_model"]()
            if self.provider == "openrouter" and self._helpers is not None
            else (model or PRODUCT_MODEL_NAME)
        )

    def available(self) -> bool:
        if self.provider == "openrouter":
            return bool(self._or_api_key)
        return self.client is not None

    async def recognize(self, message: str, product_names: list) -> ProductPick:
        """Return the product the message refers to.

        Returns a :class:`ProductPick`:
        - ``name`` is an exact catalog product when ``in_catalog`` is True.
        - ``name`` is a raw paraphrase when the user asks for something NOT in
          the catalog (so callers can capture unmatched interest), with
          ``in_catalog`` False.
        - ``name`` is None (NO_PRODUCT) when nothing was captured.
        """
        if not message or not message.strip():
            return NO_PRODUCT
        names = [n for n in (product_names or []) if n]
        if not names:
            return NO_PRODUCT
        if not self.available():
            return NO_PRODUCT
        try:
            pick = await asyncio.to_thread(
                self._sync_recognize,
                _build_system(names),
                f'User message: "{message.strip()}"',
            )
            return self._parse(pick, names)
        except Exception as exc:
            logger.warning("ProductClassifier error: %s", exc, exc_info=True)
            return NO_PRODUCT

    def _sync_recognize(self, system_instruction: str, prompt: str):
        if self.provider == "openrouter":
            result = self._helpers["post_chat_completion"](
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
        from google.genai import types

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
    def _parse(raw, names) -> ProductPick:
        """Turn raw model output into a ProductPick.

        Exact catalog match -> in_catalog True. Otherwise the cleaned text is
        the unmatched name (unless it is a no-product signal), so we can capture
        what the user asked for even when we don't sell it.
        """
        text = raw
        if not isinstance(text, str):
            text = getattr(raw, "text", "") or ""
        text = text.strip().strip('"').strip("'")
        if not text:
            return NO_PRODUCT
        if text.lower() in ("none", "null", "n/a", "no product", "no match"):
            return NO_PRODUCT
        norm = {n.lower(): n for n in names}
        if text.lower() in norm:
            return ProductPick(norm[text.lower()], True)
        m = re.search(r"\{(.*?)\}", text, re.DOTALL)
        if m:
            return ProductClassifier._parse(m.group(1).strip(), names)
        # Not an exact catalog product: keep the raw name as unmatched interest.
        return ProductPick(text, False)


def _build_system(names: list) -> str:
    listing = "\n".join(f"- {n}" for n in names)
    return (
        "You identify which product a user is asking about for Old Mutual Uganda.\n"
        "If the user is clearly asking about one of the products below, reply with\n"
        "ONLY that product's exact name from the list (verbatim), picking the single\n"
        "best match. Do not invent, combine, or modify product names.\n"
        "If the user is asking about a product or cover that is NOT in the list\n"
        "(for example a loan, health insurance, education, or some other product we\n"
        "do not carry), reply with a short plain name of what they asked for (your\n"
        "best guess, otherwise somewhat verbatim, e.g. 'health insurance').\n"
        "If the message does not indicate any product at all, reply exactly 'none'.\n\n"
        "Products:\n"
        f"{listing}"
    ).strip()
