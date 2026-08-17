import pytest

from src.chatbot.intent_classifier import IntentRouter


class FakeClient:
    """Minimal stand-in for a Gemini client returning a fixed text."""

    def __init__(self, text=None, raise_on=False):
        self._text = text
        self._raise_on = raise_on

        class _Models:
            def __init__(self, owner):
                self._owner = owner

            def generate_content(self, model=None, contents=None, config=None):
                if self._owner._raise_on:
                    raise RuntimeError("boom")

                class _Resp:
                    text = self._owner._text

                return _Resp()

        self.models = _Models(self)


@pytest.mark.asyncio
async def test_all_greetings_route_through_llm():
    router = IntentRouter(client=FakeClient('{"intent": "GREETING", "reply": "Hey there! How can I help you today?"}'))
    for msg in ["yo", "hello", "hi", "thanks", "bye"]:
        label, reply = await router.route(msg)
        assert label == "GREETING", msg
        assert reply == "Hey there! How can I help you today?"


@pytest.mark.asyncio
async def test_llm_routes_om_question_to_retrieval():
    router = IntentRouter(client=FakeClient('{"intent": "OM_QUESTION", "reply": ""}'))
    label, reply = await router.route("how do I pay my premium")
    assert label == "OM_QUESTION"
    assert reply is None


@pytest.mark.asyncio
async def test_llm_routes_quote():
    router = IntentRouter(client=FakeClient('{"intent": "QUOTE", "reply": ""}'))
    label, reply = await router.route("I want a quote for motor private")
    assert label == "QUOTE"
    assert reply is None


@pytest.mark.asyncio
async def test_llm_routes_greeting_with_reply():
    router = IntentRouter(client=FakeClient('{"intent": "GREETING", "reply": "Hey! How can I help?"}'))
    label, reply = await router.route("howzit my guy")
    assert label == "GREETING"
    assert reply == "Hey! How can I help?"


@pytest.mark.asyncio
async def test_llm_routes_off_topic_with_reply():
    router = IntentRouter(client=FakeClient('{"intent": "OFF_TOPIC", "reply": "I only help with Old Mutual."}'))
    label, reply = await router.route("what is the weather today")
    assert label == "OFF_TOPIC"
    assert reply == "I only help with Old Mutual."


@pytest.mark.asyncio
async def test_llm_malformed_json_returns_unknown():
    router = IntentRouter(client=FakeClient("definitely not json"))
    label, reply = await router.route("random message")
    assert label == "UNKNOWN"
    assert reply is None


@pytest.mark.asyncio
async def test_llm_unknown_label_returns_unknown():
    router = IntentRouter(client=FakeClient('{"intent": "WEATHER", "reply": "sunny"}'))
    label, reply = await router.route("weather?")
    assert label == "UNKNOWN"
    assert reply is None


@pytest.mark.asyncio
async def test_llm_failure_returns_unknown():
    router = IntentRouter(client=FakeClient(text="x", raise_on=True))
    label, reply = await router.route("anything")
    assert label == "UNKNOWN"
    assert reply is None
