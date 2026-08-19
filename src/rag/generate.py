import os
import logging
import asyncio
import random
from typing import Any, Dict, List, Tuple

from src.utils.llm_provider import (
    openrouter_api_key,
    openrouter_base_url,
    openrouter_model,
    openrouter_session,
)
from src.utils.response_safety import (
    looks_truncated,
    merge_continuation,
    strip_meta_lead_in,
)


# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default text generation model for Google Gemini via google-genai.
# Override at runtime with the MIA_MODEL env var.
MODEL_NAME = os.getenv("MIA_MODEL", "gemini-3.6-flash")

# LLM provider selection: "gemini" (default, current behavior) or "openrouter"
# (OpenAI-compatible pay-per-use gateway - no hard daily quota).
# Read fresh inside MiaGenerator.__init__ so runtime env changes take effect.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()

# Reserved last-resort replies. The "can't answer" message is only used when no
# LLM is available at all (generation disabled/failed hard); normally the LLM
# phrases the can't-answer + agent offer itself. The error message is reserved
# for genuine system errors (LLM API failures / empty output), never for the
# "no relevant chunks" case.
CANNOT_ANSWER_MESSAGE = (
    "I'm sorry, I can't answer that. Would you like me to connect you with an "
    "agent who can give you more information?"
)

ERROR_RETRY_MESSAGE = (
    "I'm having trouble retrieving those details right now. Please try again in a moment."
)


def is_system_error_answer(text: str) -> bool:
    """True when the reply is the reserved 'system error' retry message."""
    lowered = (text or "").strip().lower()
    return bool(lowered) and "please try again in a moment" in lowered


def classify_generation_error(exc: Exception) -> str:
    """Map a generator exception to a coarse error bucket for analytics."""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if any(k in name or k in text for k in ("resour", "quota", "429", "rate limit", "exhausted")):
        return "quota"
    if any(k in name or k in text for k in ("timeout", "deadline", "readtimeout")):
        return "timeout"
    return "exception"


SYSTEM_INSTRUCTION = """
You are MIA, the Senior Virtual Assistant for Old Mutual Uganda.
CRITICAL RULES:
1. **Only answer from the Retrieved Data**. Do not use external knowledge.
2. **SYNTHESIZE information** from the Retrieved Data - DO NOT copy text verbatim.
3. **NEVER repeat section headings** from sources (e.g., "What is X?", "Q:", "A:", "How I do apply?")
4. **Reformulate in your own words** - provide a natural conversational answer.
5. **Combine information** from multiple sources into a coherent response. Some of the
   Retrieved Data may be irrelevant to the question - use only the chunks that are
   relevant and ignore the rest.
6. Reply like an Old Mutual insider: state facts confidently as product knowledge. NEVER
   mention the Retrieved Data, a knowledge base, search results, sources, documents, or any
   "available information" in your reply. Never open a reply by describing what information
   is or isn't available.
   When a requested detail can't be confirmed from our information, respond like a confident,
   reassuring insider. NEVER say "not published", "not covered", "not in our guide", or
   anything that suggests you lack knowledge. NEVER repeat the same fallback wording twice -
   vary your phrasing naturally each time, matching the customer's tone. Acknowledge their
   question, briefly share what we DO know clearly and helpfully, then invite their next
   question ("Is there anything else I can help you with?"). Only include account numbers,
   prices, or dates that appear explicitly in the Retrieved Data - never fabricate them.
   When a number is in the sources, state it clearly.

7. **NEVER VOLUNTEER DATES.** Do NOT add "As of [date]" or "as of the year ..." to ordinary
   answers. Answer naturally and conversationally without mentioning any date. The date is
   used ONLY in rule 8, when a customer is disputing what they know against our information.
8. **WHEN A CUSTOMER DISPUTES OR YOU CANNOT ANSWER.**
   - If the customer says something that differs from our current information (e.g. "I used to
     do X, why is it not working now?"), never argue and never guess. State what our current
     information shows WITH its date: "As of [date], we do this and that." Then offer to help
     with anything else.
   - If you genuinely cannot answer a question, do NOT mention a date and NEVER sound
     uncertain or helpless. Answer confidently from what you do know and invite the customer's
     next question. Vary your wording each time (see rule 6).

9. **HUMAN AGENT AND LINKS.**
   - You are expected to answer customer questions yourself - that is your job. Never suggest,
     offer, or volunteer connecting the customer to a human agent on your own in normal
     conversation.
   - The ONLY times an agent may be mentioned are: the customer themselves asks to speak to an
     agent, says their question has not been answered, says they are unsatisfied, or explicitly
     declines the completion question ("did I answer everything?").
   - When the customer is unsatisfied or struggling to find something on the website, offer
     both a source link and the option to speak to an agent. When you have a URL in the
     Retrieved Data above, include the FULL URL in your response. For example: "You can find
     more details here: https://www.oldmutual.co.ug/..." — use the actual URL from the source
     data, never a placeholder like [link]. If no URL is available, do not say "here" or
     "click here" — just answer without a link.
   - **NEVER make up or guess URLs.** Only include a link when one is explicitly present in the
     Retrieved Data above. Do not fabricate links under any circumstances.

FORMAT:
- Use bullet points for lists of features/benefits
- Use **bold** for key terms and product names
- Keep responses under 12 lines when possible
- Write in paragraphs for explanations, bullets for lists

TONE: Professional, friendly, helpful, and conversational. Avoid robotic or scripted language.
Speak like a knowledgeable insider - never like a search engine reporting results.

EXAMPLE OF GOOD RESPONSE:
"Serenicare is Old Mutual's comprehensive health insurance plan that covers dental, optical, outpatient, and inpatient care across East Africa.
It includes coverage for chronic conditions like diabetes and HIV/AIDS, plus maternity benefits and emergency evacuation services within Uganda."

EXAMPLE OF BAD RESPONSE (never do this):
"Based on the retrieved information, Serenicare provides benefits like...
Q: Who can get the cover?
A: This product offers..."
""".strip()


class MiaGenerator:
    provider: str = "gemini"
    openrouter_model: str = ""

    def __init__(
        self,
        max_context_chars: int = 12000,
        min_score: float = 0.55,
        max_sources: int = 5,
        temperature: float = 0.2  # Lowered for financial accuracy
    ):
        self.provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
        if self.provider == "openrouter":
            if not openrouter_api_key():
                raise RuntimeError("CRITICAL: OPENROUTER_API_KEY is missing.")
            self.openrouter_api_key = openrouter_api_key()
            self.openrouter_base_url = openrouter_base_url()
            self.openrouter_model = openrouter_model()
            self.openrouter_timeout = 180
            # Ignore HTTP(S)_PROXY/ALL_PROXY env vars (e.g. PaaS-hosted services)
            # so the OpenRouter call always goes direct.
            self._http = openrouter_session()
        else:
            from google import genai
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError("CRITICAL: GEMINI_API_KEY is missing.")

            self.client = genai.Client(api_key=api_key)

        self.max_context_chars = max_context_chars
        self.min_score = min_score
        self.max_sources = max_sources
        self.temperature = temperature
        self.last_error_kind: Optional[str] = None

    def _build_history_summary(self, conversation_history: List[Dict]) -> str:
        if not conversation_history:
            return ""

        last_user = ""
        last_assistant = ""
        for msg in reversed(conversation_history):
            role = msg.get("role")
            content = (msg.get("content") or "").strip()
            if role == "assistant" and not last_assistant and content:
                last_assistant = content
            if role == "user" and not last_user and content:
                last_user = content
            if last_user and last_assistant:
                break

        if not last_user and not last_assistant:
            return ""

        def _shorten(text: str, max_len: int = 240) -> str:
            cleaned = " ".join(text.split())
            if len(cleaned) <= max_len:
                return cleaned
            return cleaned[: max_len - 3].rstrip() + "..."

        parts = []
        if last_user:
            parts.append(f"User asked about: {_shorten(last_user)}")
        if last_assistant:
            parts.append(f"Assistant replied: {_shorten(last_assistant)}")
        return " | ".join(parts)

    def _build_context(self, hits: List[Dict[str, Any]]) -> Tuple[str, int, float]:
        if not hits:
            return "", 0, 0.0

        filtered_hits = [h for h in hits if h.get("score", 0) >= self.min_score]
        if not filtered_hits:
            # If filtering by score removes all hits, use all hits anyway (better than nothing)
            logger.warning(f"All hits below min_score {self.min_score}, using all {len(hits)} hits anyway")
            filtered_hits = hits

        filtered_hits.sort(key=lambda x: x.get("score", 0), reverse=True)
        avg_score = sum(h.get("score", 0) for h in filtered_hits) / len(filtered_hits)

        # Load chunk texts from file if payload doesn't contain text field
        chunk_texts = self._load_chunk_texts_if_needed(filtered_hits)

        context_parts = []
        current_length = 0
        sources_used = 0

        for idx, h in enumerate(filtered_hits[:self.max_sources], 1):
            p = h.get("payload") or h
            chunk_id = h.get("id") or p.get("id")

            # Try to get text from payload first, then from loaded chunks
            text = p.get("text", "").strip()
            if not text and chunk_id in chunk_texts:
                text = chunk_texts[chunk_id]

            if not text:
                logger.warning(f"No text found for chunk {chunk_id}, skipping")
                continue

            chunk = f"[Source {idx}] **{p.get('title', 'Unknown')}**"
            as_of = p.get("as_of")
            if as_of:
                chunk += f" (as of {as_of})"
            url = p.get("url")
            if url:
                chunk += f" | URL: {url}"
            chunk += f": {text}\n"
            if current_length + len(chunk) > self.max_context_chars:
                break
            context_parts.append(chunk)
            current_length += len(chunk)
            sources_used += 1

        return "\n".join(context_parts), sources_used, avg_score

    def _load_chunk_texts_if_needed(self, hits: List[Dict[str, Any]]) -> Dict[str, str]:
        """Load chunk texts from website_chunks.jsonl when payload doesn't contain text."""
        import json
        from pathlib import Path

        # Check if any hit is missing text in payload
        needs_loading = False
        for h in hits:
            p = h.get("payload") or h
            if not p.get("text"):
                needs_loading = True
                break

        if not needs_loading:
            return {}

        # Collect IDs that need text
        needed_ids = set()
        for h in hits:
            p = h.get("payload") or h
            if not p.get("text"):
                chunk_id = h.get("id") or p.get("id")
                if chunk_id:
                    needed_ids.add(chunk_id)

        if not needed_ids:
            return {}

        # Load from chunks file
        chunks_path = Path(__file__).parent.parent.parent / "data" / "processed" / "website_chunks.jsonl"
        chunk_texts = {}

        if not chunks_path.exists():
            logger.warning(f"Chunks file not found: {chunks_path}")
            return {}

        try:
            with open(chunks_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                        chunk_id = chunk.get("id")
                        if chunk_id in needed_ids:
                            chunk_texts[chunk_id] = chunk.get("text", "")
                            if len(chunk_texts) >= len(needed_ids):
                                break  # Found all needed chunks
                    except json.JSONDecodeError:
                        continue

            logger.info(f"Loaded {len(chunk_texts)} chunk texts from file")
            return chunk_texts
        except Exception as e:
            logger.error(f"Error loading chunk texts: {e}")
            return {}

    def _extract_response(self, response):
        """Normalize a provider response into (text, finish_reason)."""
        if self.provider == "openrouter":
            text = ""
            finish_reason = None
            choices = (response or {}).get("choices") or []
            if choices:
                first = choices[0]
                message = first.get("message") or {}
                text = str(message.get("content") or "").strip()
                finish_reason = first.get("finish_reason")
            return text, finish_reason

        text = (getattr(response, "text", "") or "").strip()
        finish_reason = None
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            fr = getattr(candidates[0], "finish_reason", None)
            # Gemini SDK may return an enum or a plain int; MAX_TOKENS = 2
            finish_reason = getattr(fr, "value", fr)
        return text, finish_reason

    async def generate(self, question: str, hits: List[Dict[str, Any]], conversation_history: List[Dict] = None) -> str:
        self.last_error_kind = None
        context, num_sources, _ = self._build_context(hits)

        context_note = (
            f"**Instructions:** Using the {num_sources} source(s) below, synthesize a natural conversational answer. "
            "Do NOT copy headings or Q&A format from sources - reformulate in your own words. "
            "Do not add facts not present in the sources."
            if num_sources > 0
            else (
                "You have no reference material for this question. Do NOT mention documents, "
                "searches, a knowledge base, or any available/retrieved information. Answer as "
                "an Old Mutual specialist would: share what you do know, and if the detail is "
                "genuinely not something we publish, say so naturally and invite the user's "
                "next question. Never offer to connect the user with a human agent unless the "
                "user explicitly asks for one."
            )
        )

        # Keep history compact and avoid duplicating the same context as both
        # free-form summary and transcript.
        history_text = ""
        if conversation_history:
            history_lines = []
            for msg in conversation_history[-6:]:
                role = msg.get("role", "user")
                content = " ".join((msg.get("content") or "").split())
                if not content:
                    continue
                if len(content) > 280:
                    content = content[:277].rstrip() + "..."
                if role == "user":
                    history_lines.append(f"User: {content}")
                elif role == "assistant":
                    history_lines.append(f"Assistant: {content}")

            if history_lines:
                history_text = "\n\n**Recent Conversation:**\n" + "\n".join(history_lines)
            else:
                summary = self._build_history_summary(conversation_history)
                if summary:
                    history_text = f"\n\n**Conversation Summary:** {summary}"

        full_prompt = (
            f"{context_note}{history_text}\n\n"
            f"**User Question:** {question}\n\n"
            f"**Retrieved Data:**\n{context or 'None'}"
        )

        logger.info(f"Generating response for question: {question[:100]}... with {num_sources} sources")

        def _sync_generate(prompt: str, max_output_tokens: int = 1200):
            if self.provider == "openrouter":
                http_response = self._http.post(
                    f"{self.openrouter_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.openrouter_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.openrouter_model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_INSTRUCTION},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": self.temperature,
                        "max_tokens": max_output_tokens,
                    },
                    timeout=self.openrouter_timeout,
                )
                if http_response.status_code != 200:
                    raise RuntimeError(
                        f"OpenRouter HTTP {http_response.status_code}: {http_response.text[:300]}"
                    )
                return http_response.json()

            from google.genai import types
            response = self.client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=self.temperature,
                    max_output_tokens=max_output_tokens,
                ),
            )
            return response

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                response = await asyncio.to_thread(_sync_generate, full_prompt, 1200)
                text, finish_reason = self._extract_response(response)
                if not text:
                    logger.warning("LLM returned empty text response.")
                    self.last_error_kind = "empty_output"
                    return ERROR_RETRY_MESSAGE

                # Request a continuation only when the provider reports the output
                # was cut off at the token budget (Gemini finish_reason MAX_TOKENS = 2;
                # OpenAI-style "length"). Checking the API field is far more reliable
                # than text heuristics and avoids wasteful extra API calls on
                # already-complete answers.
                hit_token_limit = False
                try:
                    if self.provider == "openrouter":
                        if finish_reason == "length":
                            hit_token_limit = True
                            logger.info("OpenRouter hit max_output_tokens; requesting continuation")
                    elif finish_reason == 2:
                        hit_token_limit = True
                        logger.info("Gemini hit max_output_tokens; requesting continuation")
                except Exception:
                    # If we cannot read finish_reason, fall back to text heuristic.
                    hit_token_limit = self._looks_truncated(text)
                if hit_token_limit:
                    try:
                        continuation_prompt = (
                            "Continue the answer from where it stopped. "
                            "Do not repeat the text already provided. "
                            "Finish the incomplete thought in 1-3 short sentences.\n\n"
                            f"Current partial answer:\n{text}"
                        )
                        continuation = await asyncio.to_thread(_sync_generate, continuation_prompt, 300)
                        continuation_text, _ = self._extract_response(continuation)
                        if continuation_text:
                            text = self._merge_continuation(text, continuation_text)
                    except Exception as continuation_error:
                        logger.warning("Continuation attempt failed: %s", continuation_error)

                logger.info(
                    "Successfully generated response from %s API",
                    "OpenRouter" if self.provider == "openrouter" else "Gemini",
                )
                return strip_meta_lead_in(text)
            except Exception as e:
                self.last_error_kind = classify_generation_error(e)
                if attempt >= max_attempts:
                    logger.error(f"GenAI error when generating response: {type(e).__name__}: {e}", exc_info=True)
                    break
                backoff = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                logger.warning(
                    "GenAI request failed on attempt %s/%s (%s). Retrying in %.2fs...",
                    attempt,
                    max_attempts,
                    type(e).__name__,
                    backoff,
                )
                await asyncio.sleep(backoff)

        return ERROR_RETRY_MESSAGE

    @staticmethod
    def _looks_truncated(text: str) -> bool:
        """Deprecated alias kept for tests; use ``response_safety.looks_truncated``."""
        return looks_truncated(text)

    @staticmethod
    def _merge_continuation(base_text: str, continuation_text: str) -> str:
        """Deprecated alias kept for tests; use ``response_safety.merge_continuation``."""
        return merge_continuation(base_text, continuation_text)


def generate_with_gemini(
    *,
    question: str,
    hits: List[Dict[str, Any]],
    model: str | None = None,
    api_key_env: str = "GEMINI_API_KEY",
) -> str:
    """Sync helper used by scripts/run_rag.py."""
    import asyncio

    # Allow alternate env var names while keeping GEMINI_API_KEY as the canonical key.
    if api_key_env and api_key_env != "GEMINI_API_KEY" and not os.environ.get("GEMINI_API_KEY"):
        alt_value = os.environ.get(api_key_env)
        if alt_value:
            os.environ["GEMINI_API_KEY"] = alt_value

    global MODEL_NAME
    previous_model = MODEL_NAME
    if model:
        MODEL_NAME = model

    try:
        generator = MiaGenerator()
        return asyncio.run(generator.generate(question, hits, conversation_history=None))
    finally:
        MODEL_NAME = previous_model
