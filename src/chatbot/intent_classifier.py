import asyncio
import os
import logging
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Use the same family as the main generator for consistency.
INTENT_MODEL_NAME = "gemini-2.5-flash"


class SmallTalkResponder:
    """
    Uses the LLM to generate short, polite replies for NO_RETRIEVAL intents
    (greetings, thanks, small talk, goodbyes) without touching RAG.
    """

    def __init__(self, api_key_env: str = "GEMINI_API_KEY"):
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
