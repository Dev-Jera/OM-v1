import asyncio
from types import SimpleNamespace

import openai
import pytest

from src.rag.generate import ERROR_RETRY_MESSAGE, MiaGenerator, SYSTEM_INSTRUCTION


class _Choice:
    def __init__(self, content, finish_reason):
        self.message = SimpleNamespace(content=content)
        self.finish_reason = finish_reason


class _ChatCompletion:
    def __init__(self, choices):
        self.choices = choices


def make_fake_openai(responses):
    """Build a fake openai.OpenAI that replays a fixed list of responses."""
    class _Completions:
        def __init__(self):
            self.calls = []
            self.responses = list(responses)

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return self.responses.pop(0)

    class _Chat:
        def __init__(self):
            self.completions = _Completions()

    class _FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            self.api_key = api_key
            self.base_url = base_url
            self.chat = _Chat()

    return _FakeOpenAI


@pytest.mark.asyncio
async def test_openrouter_uses_chat_completions_with_system_instruction(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "deepseek/deepseek-chat")

    FakeOpenAI = make_fake_openai([_ChatCompletion([_Choice("OpenRouter answer", "stop")])])
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    gen = MiaGenerator()
    assert gen.provider == "openrouter"
    assert isinstance(gen.client, FakeOpenAI)
    assert gen.client.base_url == "https://openrouter.ai/api/v1"

    out = await gen.generate("what is the minimum deposit", hits=[{"id": "1"}], conversation_history=[])

    assert out == "OpenRouter answer"
    create_kwargs = gen.client.chat.completions.calls[0]
    assert create_kwargs["model"] == "deepseek/deepseek-chat"
    assert create_kwargs["messages"][0] == {"role": "system", "content": SYSTEM_INSTRUCTION}
    assert "Retrieved Data" in create_kwargs["messages"][1]["content"]


@pytest.mark.asyncio
async def test_openrouter_continuation_on_length_finish(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    first = _ChatCompletion([_Choice("First part of the answer,", "length")])
    second = _ChatCompletion([_Choice(" and the continued ending.", "stop")])
    FakeOpenAI = make_fake_openai([first, second])
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    gen = MiaGenerator()
    out = await gen.generate("question", hits=[], conversation_history=[])

    assert len(gen.client.chat.completions.calls) == 2
    assert "First part of the answer" in out
    assert "continued ending" in out


@pytest.mark.asyncio
async def test_openrouter_quota_error_maps_to_quota_and_retry_message(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    class _Completions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            raise RuntimeError("429 You exceeded your current quota")

    class _Chat:
        def __init__(self):
            self.completions = _Completions()

    class _FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            self.api_key = api_key
            self.base_url = base_url
            self.chat = _Chat()

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)

    async def _no_sleep(_):
        return None

    monkeypatch.setattr("src.rag.generate.asyncio.sleep", _no_sleep)
    monkeypatch.setattr("src.rag.generate.random.uniform", lambda _a, _b: 0.0)

    gen = MiaGenerator()
    out = await gen.generate("question", hits=[], conversation_history=[])

    assert out == ERROR_RETRY_MESSAGE
    assert gen.last_error_kind == "quota"


def test_default_provider_is_gemini(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    import google.genai as genai

    class _FakeClient:
        def __init__(self, api_key=None):
            self.api_key = api_key

    monkeypatch.setattr(genai, "Client", _FakeClient)

    gen = MiaGenerator()
    assert gen.provider == "gemini"
    assert gen.client.api_key == "test-gemini-key"
