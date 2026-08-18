import pytest

from src.rag.generate import ERROR_RETRY_MESSAGE, MiaGenerator, SYSTEM_INSTRUCTION


def _chat_completion(content, finish_reason):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]}


class _FakeResp:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body
        self.text = text

    def json(self):
        return self._json


def _patch_requests_session(monkeypatch, responses):
    captured = {"calls": []}

    class _FakeSession:
        trust_env = True

        def post(self, url=None, **kwargs):
            captured["calls"].append({"url": url, **kwargs})
            return responses.pop(0)

    monkeypatch.setattr("src.utils.llm_provider.requests.Session", lambda: _FakeSession())
    return captured


@pytest.mark.asyncio
async def test_openrouter_uses_chat_completions_with_system_instruction(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "deepseek/deepseek-chat")

    captured = _patch_requests_session(
        monkeypatch, [_FakeResp(200, _chat_completion("OpenRouter answer", "stop"))]
    )

    gen = MiaGenerator()
    assert gen.provider == "openrouter"
    assert gen.openrouter_base_url == "https://openrouter.ai/api/v1"

    out = await gen.generate("what is the minimum deposit", hits=[{"id": "1"}], conversation_history=[])

    assert out == "OpenRouter answer"
    call = captured["calls"][0]
    assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["json"]["model"] == "deepseek/deepseek-chat"
    assert call["json"]["messages"][0] == {"role": "system", "content": SYSTEM_INSTRUCTION}
    assert "Retrieved Data" in call["json"]["messages"][1]["content"]


@pytest.mark.asyncio
async def test_openrouter_continuation_on_length_finish(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    captured = _patch_requests_session(
        monkeypatch,
        [
            _FakeResp(200, _chat_completion("First part of the answer,", "length")),
            _FakeResp(200, _chat_completion(" and the continued ending.", "stop")),
        ],
    )

    gen = MiaGenerator()
    out = await gen.generate("question", hits=[], conversation_history=[])

    assert len(captured["calls"]) == 2
    assert "First part of the answer" in out
    assert "continued ending" in out


@pytest.mark.asyncio
async def test_openrouter_quota_error_maps_to_quota_and_retry_message(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    _patch_requests_session(
        monkeypatch,
        [
            _FakeResp(429, None, "You exceeded your current quota"),
            _FakeResp(429, None, "You exceeded your current quota"),
            _FakeResp(429, None, "You exceeded your current quota"),
        ],
    )

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