import pytest

from src.chatbot.brain import ConversationalBrain
from src.utils.pii_redaction import PHONE_MASK


class FakeFunctionCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args


class FakePart:
    def __init__(self, function_call=None, text=None):
        self.function_call = function_call
        self.text = text


class FakeContent:
    def __init__(self, parts, role="model"):
        self.parts = parts
        self.role = role


class FakeCandidate:
    def __init__(self, content):
        self.content = content


class FakeResponse:
    def __init__(self, parts, text=None):
        self.candidates = [FakeCandidate(FakeContent(parts))]
        if text is None:
            text = "".join(p.text for p in parts if getattr(p, "text", None)) or None
        self._text = text

    @property
    def text(self):
        if self._text is None:
            raise ValueError("response has no text")
        return self._text


def fc_part(name, args):
    return FakePart(function_call=FakeFunctionCall(name, args))


def text_part(text):
    return FakePart(text=text)


class ScriptedLLM:
    """Async fake LLM returning a scripted sequence of responses per call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []  # (contents, config)

    async def __call__(self, contents, config):
        self.calls.append((contents, config))
        if not self.responses:
            return FakeResponse([text_part("fallback reply")])
        return self.responses.pop(0)


class RecordingRetriever:
    def __init__(self, hits=None):
        self.hits = hits or [{"payload": {"title": "Doc", "text": "Serenicare covers dental and optical care."}}]
        self.queries = []

    async def __call__(self, query=None, filters=None):
        self.queries.append(query)
        return self.hits


def make_brain(llm, retriever, **kwargs):
    return ConversationalBrain(llm=llm, retrieve_fn=retriever, enabled=True, **kwargs)


@pytest.mark.asyncio
async def test_greeting_no_retrieval():
    retriever = RecordingRetriever()
    llm = ScriptedLLM([FakeResponse([text_part("Hello! How can I help you at Old Mutual today?")])])
    brain = make_brain(llm, retriever)

    result = await brain.converse("yo")
    assert result is not None
    assert "help" in result.reply.lower()
    assert result.used_knowledge is False
    assert result.quote_requested is False
    assert retriever.queries == []


@pytest.mark.asyncio
async def test_product_question_retrieves_and_grounds():
    retriever = RecordingRetriever()
    llm = ScriptedLLM(
        [
            FakeResponse([fc_part("search_knowledge_base", {"query": "Serenicare coverage"})]),
            FakeResponse([text_part("Serenicare covers dental and optical care.")]),
        ]
    )
    brain = make_brain(llm, retriever)

    result = await brain.converse("what does serenicare cover")
    assert result is not None
    assert "dental" in result.reply
    assert result.used_knowledge is True
    assert len(result.sources) == 1
    assert retriever.queries == ["Serenicare coverage"]


@pytest.mark.asyncio
async def test_quote_request_triggers_guided_quote():
    retriever = RecordingRetriever()
    llm = ScriptedLLM(
        [
            FakeResponse([fc_part("request_guided_quote", {"product": "travel_insurance"})]),
            FakeResponse([text_part("Great! Click the button below to load the form and get your quotation.")]),
        ]
    )
    brain = make_brain(llm, retriever)

    result = await brain.converse("i want a quote for travel insurance")
    assert result is not None
    assert result.quote_requested is True
    assert result.product == "travel_insurance"
    assert retriever.queries == []


@pytest.mark.asyncio
async def test_off_topic_steers_back():
    retriever = RecordingRetriever()
    llm = ScriptedLLM([FakeResponse([text_part("I only help with Old Mutual products and services.")])])
    brain = make_brain(llm, retriever)

    result = await brain.converse("what is the weather today")
    assert result is not None
    assert "old mutual" in result.reply.lower()
    assert retriever.queries == []


@pytest.mark.asyncio
async def test_message_is_pii_redacted_before_llm():
    retriever = RecordingRetriever()
    llm = ScriptedLLM([FakeResponse([text_part("Thanks for letting me know.")])])
    brain = make_brain(llm, retriever)

    await brain.converse("my phone is 0771234567")
    contents = llm.calls[0][0]
    joined = " ".join(p["parts"][0]["text"] for p in contents)
    assert PHONE_MASK in joined
    assert "0771234567" not in joined


@pytest.mark.asyncio
async def test_history_is_redacted_and_form_payloads_filtered():
    retriever = RecordingRetriever()
    llm = ScriptedLLM([FakeResponse([text_part("ok")])])
    brain = make_brain(llm, retriever)

    history = [
        {"role": "user", "content": "my phone 0771234567"},
        {"role": "user", "content": "Submitted details:\n- Full name: Sarah\n- Phone: 0771234567"},
        {"role": "user", "content": "thanks"},
    ]
    await brain.converse("hi", history=history)

    contents = llm.calls[0][0]
    joined = " ".join(p["parts"][0]["text"] for p in contents)
    assert PHONE_MASK in joined
    assert "0771234567" not in joined
    assert "Sarah" not in joined
    assert "Submitted details" not in joined


@pytest.mark.asyncio
async def test_confirm_quote_offer_proceed():
    retriever = RecordingRetriever()
    llm = ScriptedLLM([FakeResponse([text_part('{"decision": "proceed"}')])])
    brain = make_brain(llm, retriever)

    decision = await brain.confirm_quote_offer("yes please")
    assert decision == "proceed"


@pytest.mark.asyncio
async def test_confirm_quote_offer_cancel():
    retriever = RecordingRetriever()
    llm = ScriptedLLM([FakeResponse([text_part('{"decision": "cancel"}')])])
    brain = make_brain(llm, retriever)

    decision = await brain.confirm_quote_offer("no thanks")
    assert decision == "cancel"


@pytest.mark.asyncio
async def test_confirm_quote_offer_other_on_bad_json():
    retriever = RecordingRetriever()
    llm = ScriptedLLM([FakeResponse([text_part("not json at all")])])
    brain = make_brain(llm, retriever)

    decision = await brain.confirm_quote_offer("hi")
    assert decision == "other"


@pytest.mark.asyncio
async def test_disabled_brain_returns_none():
    retriever = RecordingRetriever()
    llm = ScriptedLLM([])
    brain = ConversationalBrain(llm=llm, retrieve_fn=retriever, enabled=False)

    assert await brain.converse("hi") is None
    assert await brain.confirm_quote_offer("yes") == "other"


def test_quote_tool_enum_has_no_empty_string():
    """Gemini rejects function-declaration enums containing an empty string
    (400 INVALID_ARGUMENT ... enum[0]: cannot be empty). The 'unknown'
    sentinel must stand in for the previous empty-string value."""
    retriever = RecordingRetriever()
    brain = make_brain(ScriptedLLM([]), retriever)

    config = brain._conversation_config(pending_quote_offer=False)
    tools = config["tools"]
    declarations = [
        d
        for tool in tools
        for d in tool.get("function_declarations", [])
        if d["name"] == "request_guided_quote"
    ]
    assert len(declarations) == 1
    enum = declarations[0]["parameters"]["properties"]["product"]["enum"]
    assert enum == ["unknown"] + ["personal_accident", "travel_insurance", "motor_private", "serenicare"]
    assert "" not in enum


@pytest.mark.asyncio
async def test_empty_reply_returns_none():
    retriever = RecordingRetriever()
    llm = ScriptedLLM([FakeResponse([text_part("")])])
    brain = make_brain(llm, retriever)

    assert await brain.converse("hello") is None


@pytest.mark.asyncio
async def test_truncated_reply_requests_continuation():
    retriever = RecordingRetriever()
    llm = ScriptedLLM(
        [
            FakeResponse(
                [
                    text_part(
                        "I understand you're having trouble logging into your self-service portal "
                        "for the Unit Trust. Our available information doesn't specifically detail "
                        "how to fix login problems. However"
                    )
                ]
            ),
            FakeResponse([text_part(" here are the steps to access your portal.")]),
        ]
    )
    brain = make_brain(llm, retriever)

    result = await brain.converse("how do i log into the unit trust portal")

    assert result is not None
    assert len(llm.calls) == 2
    assert "steps to access" in result.reply
    assert "available information" not in result.reply
    assert not result.reply.rstrip().endswith("However")


@pytest.mark.asyncio
async def test_complete_reply_does_not_trigger_continuation():
    retriever = RecordingRetriever()
    llm = ScriptedLLM(
        [FakeResponse([text_part("You can fund the Balanced Fund by direct debit, M-Pesa, cheque, or standing order.")])]
    )
    brain = make_brain(llm, retriever)

    result = await brain.converse("how can i fund the balanced fund")

    assert result is not None
    assert len(llm.calls) == 1
    assert "direct debit" in result.reply


@pytest.mark.asyncio
async def test_meta_lead_in_stripped_from_reply():
    retriever = RecordingRetriever()
    llm = ScriptedLLM(
        [
            FakeResponse(
                [
                    text_part(
                        "Our available information doesn't specifically detail that. However, you "
                        "can fund the Balanced Fund by direct debit."
                    )
                ]
            )
        ]
    )
    brain = make_brain(llm, retriever)

    result = await brain.converse("can i fund via m-pesa")

    assert result is not None
    assert "available information" not in result.reply
    assert result.reply.startswith("You can fund the Balanced Fund")
