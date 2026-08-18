"""Shared helpers for the Gemini / OpenRouter LLM provider switch.

LLM_PROVIDER=gemini (default) keeps the existing Google Gemini clients.
LLM_PROVIDER=openrouter routes generation through the OpenAI-compatible
OpenRouter gateway (pay-per-use, no hard daily quota). Env values are
defensively cleaned so paste artifacts (surrounding backticks/quotes) cannot
break the request.
"""

import os

import requests

DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-chat"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def clean_env_value(value) -> str:
    """Strip whitespace and a single wrapping pair of quotes or backticks."""
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'", "`"):
        value = value[1:-1].strip()
    return value


def is_openrouter_enabled() -> bool:
    return clean_env_value(os.getenv("LLM_PROVIDER", "gemini")).lower() == "openrouter"


def openrouter_api_key() -> str:
    return clean_env_value(os.environ.get("OPENROUTER_API_KEY", ""))


def openrouter_model() -> str:
    return clean_env_value(os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL))


def openrouter_base_url() -> str:
    return clean_env_value(os.getenv("OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL)).rstrip("/")


def openrouter_session() -> requests.Session:
    """A requests session that ignores HTTP(S)_PROXY/ALL_PROXY env vars."""
    session = requests.Session()
    session.trust_env = False
    return session


def post_chat_completion(
    *,
    session: requests.Session,
    base_url: str,
    api_key: str,
    model: str,
    messages: list,
    temperature: float,
    max_tokens: int,
    tools: list = None,
    timeout: int = 180,
) -> dict:
    """POST an OpenAI-compatible chat completion; raise on non-200."""
    body: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools
    http_response = session.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=timeout,
    )
    if http_response.status_code != 200:
        raise RuntimeError(f"OpenRouter HTTP {http_response.status_code}: {http_response.text[:300]}")
    return http_response.json()
