import pytest

from src.chatbot.brain import ConversationalBrain
from src.chatbot.intent_classifier import IntentRouter, SmallTalkResponder


def make_response(content=None, tool_calls=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def search_tool_call(query):
    return {
        "id": "call_1",
        "type": "function",
        "function": {"name": "search_knowledge_base", "arguments": f'{{"query": "{query}"}}'},
    }


def quote_tool_call(product):
    return {
        "id": "call_2",
        "type": "function",
        "function": {"name": "request_guided_quote", "arguments": f'{{"product": "{product}"}}'},
    }


class ScriptedPoster:
    """Sync fake for post_chat_completion returning a scripted sequence."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, *, session, base_url, api_key, model, messages, temperature, max_tokens, tools=None, timeout=180):
        self.calls.append(messages)
        if not self.responses:
            return make_response(content="fallback reply")
        return self.responses.pop(0)


class RecordingRetriever:
    def __init__(self, hits=None):
        self.hits = hits or [{"payload": {"title": "Doc", "text": "Serenicare covers dental and optical care."}}]
        self.queries = []

    async def __call__(self, query=None, filters=None):
        self.queries.append(query)
        return self.hits


@pytest.fixture
def openrouter_env(monkeypatch):
    monkeypatch.setattr("src.chatbot.brain.is_openrouter_enabled", lambda: True)
    monkeypatch.setattr("src.chatbot.brain.openrouter_api_key", lambda: "test-key")
    monkeypatch.setattr("src.chatbot.intent_classifier.is_openrouter_enabled", lambda: True)
    monkeypatch.setattr("src.chatbot.intent_classifier.openrouter_api_key", lambda: "test-key")


def make_openrouter_brain(monkeypatch, poster, retriever):
    monkeypatch.setattr("src.chatbot.brain.post_chat_completion", poster)
    brain = ConversationalBrain(llm=None, retrieve_fn=retriever, enabled=True)
    assert brain.provider == "openrouter"
    return brain


@pytest.mark.asyncio
async def test_openrouter_brain_retrieves_and_grounds(openrouter_env, monkeypatch):
    retriever = RecordingRetriever()
    poster = ScriptedPoster(
        [
            make_response(tool_calls=[search_tool_call("Serenicare coverage")]),
            make_response(content="Serenicare covers dental and optical care."),
        ]
    )
    brain = make_openrouter_brain(monkeypatch, poster, retriever)

    result = await brain.converse("what does serenicare cover")

    assert result is not None
    assert "dental" in result.reply
    assert result.used_knowledge is True
    assert len(result.sources) == 1
    assert retriever.queries == ["Serenicare coverage"]
    assert poster.calls[0][0]["role"] == "system"
    assert any(m.get("role") == "tool" for m in poster.calls[1])


@pytest.mark.asyncio
async def test_openrouter_brain_quote_request(openrouter_env, monkeypatch):
    retriever = RecordingRetriever()
    poster = ScriptedPoster(
        [
            make_response(tool_calls=[quote_tool_call("travel_insurance")]),
            make_response(content="Great! Click the button below to load the form."),
        ]
    )
    brain = make_openrouter_brain(monkeypatch, poster, retriever)

    result = await brain.converse("i want a quote for travel insurance")

    assert result is not None
    assert result.quote_requested is True
    assert result.product == "travel_insurance"
    assert retriever.queries == []


@pytest.mark.asyncio
async def test_openrouter_brain_empty_reply_returns_none(openrouter_env, monkeypatch):
    retriever = RecordingRetriever()
    poster = ScriptedPoster([make_response(content="")])
    brain = make_openrouter_brain(monkeypatch, poster, retriever)

    assert await brain.converse("hello") is None


@pytest.mark.asyncio
async def test_openrouter_brain_strips_meta_lead_in(openrouter_env, monkeypatch):
    retriever = RecordingRetriever()
    poster = ScriptedPoster(
        [
            make_response(
                content=(
                    "Our available information doesn't specifically detail that. However, you "
                    "can fund the Balanced Fund by direct debit."
                )
            )
        ]
    )
    brain = make_openrouter_brain(monkeypatch, poster, retriever)

    result = await brain.converse("can i fund via m-pesa")

    assert result is not None
    assert "available information" not in result.reply
    assert result.reply.startswith("You can fund the Balanced Fund")


@pytest.mark.asyncio
async def test_openrouter_brain_confirm_quote_proceed(openrouter_env, monkeypatch):
    retriever = RecordingRetriever()
    poster = ScriptedPoster([make_response(content='{"decision": "proceed"}')])
    brain = make_openrouter_brain(monkeypatch, poster, retriever)

    assert await brain.confirm_quote_offer("yes please") == "proceed"


@pytest.mark.asyncio
async def test_openrouter_brain_confirm_quote_bad_json_other(openrouter_env, monkeypatch):
    retriever = RecordingRetriever()
    poster = ScriptedPoster([make_response(content="not json at all")])
    brain = make_openrouter_brain(monkeypatch, poster, retriever)

    assert await brain.confirm_quote_offer("hi") == "other"


@pytest.mark.asyncio
async def test_openrouter_intent_router_om_question(openrouter_env, monkeypatch):
    monkeypatch.setattr(
        "src.chatbot.intent_classifier.post_chat_completion",
        ScriptedPoster([make_response(content='{"intent": "OM_QUESTION", "reply": ""}')]),
    )
    router = IntentRouter()
    label, reply = await router.route("what does serenicare cover")
    assert label == "OM_QUESTION"
    assert reply is None


@pytest.mark.asyncio
async def test_openrouter_intent_router_greeting(openrouter_env, monkeypatch):
    monkeypatch.setattr(
        "src.chatbot.intent_classifier.post_chat_completion",
        ScriptedPoster([make_response(content='{"intent": "GREETING", "reply": "Hello there!"}')]),
    )
    router = IntentRouter()
    label, reply = await router.route("hello")
    assert label == "GREETING"
    assert reply == "Hello there!"


@pytest.mark.asyncio
async def test_openrouter_small_talk_responder(openrouter_env, monkeypatch):
    monkeypatch.setattr(
        "src.chatbot.intent_classifier.post_chat_completion",
        ScriptedPoster([make_response(content="I can only help with Old Mutual products.")]),
    )
    responder = SmallTalkResponder()
    reply = await responder.respond("how are you", label="SMALL_TALK")
    assert "Old Mutual" in reply