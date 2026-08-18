import pytest

from src.chatbot.modes.conversational import ConversationalMode
from src.chatbot.state_manager import StateManager
from src.database.postgres import PostgresDB
from src.database.redis import RedisCache


class DummyRAG:
    async def retrieve(self, query: str, filters=None, top_k=None):
        return []

    async def generate(self, query: str, context_docs, conversation_history):
        return {"answer": f"LEGACY: {query}", "confidence": 0.5, "sources": []}


class DummyMatcher:
    def match_products(self, query: str, top_k: int = 3):
        return []


class DummyBrain:
    """Fake brain recording calls and returning a scripted result."""

    def __init__(self, result=None, decision="other"):
        self.result = result
        self.decision = decision
        self.converse_calls = []
        self.confirm_calls = []

    async def converse(self, message=None, history=None, topic=None, pending_quote_offer=False):
        self.converse_calls.append(
            {"message": message, "history": history, "topic": topic, "pending_quote_offer": pending_quote_offer}
        )
        return self.result

    async def confirm_quote_offer(self, message=None, history=None):
        self.confirm_calls.append({"message": message, "history": history})
        return self.decision


class SimpleResult:
    def __init__(
        self,
        reply="brain reply",
        confidence=0.8,
        sources=None,
        quote_requested=False,
        product=None,
        used_knowledge=False,
    ):
        self.reply = reply
        self.confidence = confidence
        self.sources = sources or []
        self.quote_requested = quote_requested
        self.product = product
        self.used_knowledge = used_knowledge


class DummyRouter:
    """Fake intent router returning a scripted label/reply."""

    def __init__(self, label="OM_QUESTION", reply=None):
        self.label = label
        self.reply = reply
        self.calls = []

    async def route(self, message):
        self.calls.append(message)
        return self.label, self.reply


def make_session(sm, user_id="1"):
    session_id = sm.create_session(user_id)
    return session_id


@pytest.mark.asyncio
async def test_free_text_routes_through_brain_when_attached():
    db = PostgresDB()
    sm = StateManager(RedisCache(), db)
    session_id = make_session(sm)
    brain = DummyBrain(result=SimpleResult(reply="Brain understands this naturally."))
    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm, brain=brain)

    out = await conv.process("what does serenicare cover", session_id, "1")

    assert out["mode"] == "conversational"
    assert out["response"] == "Brain understands this naturally."
    assert out.get("brain") is True
    assert len(brain.converse_calls) == 1
    assert brain.converse_calls[0]["message"] == "what does serenicare cover"


@pytest.mark.asyncio
async def test_legacy_path_used_when_no_brain():
    db = PostgresDB()
    sm = StateManager(RedisCache(), db)
    session_id = make_session(sm)
    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm)

    out = await conv.process("hello there", session_id, "1")

    assert out["mode"] == "conversational"
    # No brain attached -> legacy RAG path answers; the DummyRAG mock tags its
    # answer with "LEGACY:" to prove the legacy path was used (not the brain).
    assert "LEGACY" in (out.get("response") or "")
    assert out.get("brain") is not True


@pytest.mark.asyncio
async def test_brain_disabled_falls_back_to_legacy():
    db = PostgresDB()
    sm = StateManager(RedisCache(), db)
    session_id = make_session(sm)
    brain = DummyBrain(result=None)  # brain returns None -> unusable
    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm, brain=brain)

    out = await conv.process("tell me about a product", session_id, "1")

    assert out["mode"] == "conversational"
    assert out.get("brain") is not True


@pytest.mark.asyncio
async def test_quote_request_returns_guided_suggested_action_and_sets_pending():
    db = PostgresDB()
    sm = StateManager(RedisCache(), db)
    session_id = make_session(sm)
    brain = DummyBrain(result=SimpleResult(reply="Sure, click below.", quote_requested=True, product="travel_insurance"))
    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm, brain=brain)

    out = await conv.process("i want a travel insurance quotation", session_id, "1")

    assert out["intent"] == "quote"
    assert out["suggested_action"]["type"] == "switch_to_guided"
    assert out["suggested_action"]["initial_data"]["product_flow"] == "travel_insurance"
    session = sm.get_session(session_id)
    assert session["context"].get("pending_quote_offer") is True


@pytest.mark.asyncio
async def test_pending_quote_offer_proceed_bridge():
    db = PostgresDB()
    sm = StateManager(RedisCache(), db)
    session_id = make_session(sm)
    sm.update_session(session_id, {"context": {"pending_quote_offer": True}})
    brain = DummyBrain(decision="proceed")
    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm, brain=brain)

    out = await conv.process("yes please", session_id, "1")

    assert out["intent"] == "quote"
    assert out["suggested_action"]["type"] == "switch_to_guided"
    assert len(brain.confirm_calls) == 1
    assert len(brain.converse_calls) == 0
    session = sm.get_session(session_id)
    assert not session["context"].get("pending_quote_offer")


@pytest.mark.asyncio
async def test_pending_quote_offer_cancel_bridge():
    db = PostgresDB()
    sm = StateManager(RedisCache(), db)
    session_id = make_session(sm)
    sm.update_session(session_id, {"context": {"pending_quote_offer": True}})
    brain = DummyBrain(decision="cancel")
    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm, brain=brain)

    out = await conv.process("not now", session_id, "1")

    assert out["mode"] == "conversational"
    assert "No problem" in out["response"]
    session = sm.get_session(session_id)
    assert not session["context"].get("pending_quote_offer")


@pytest.mark.asyncio
async def test_pending_quote_offer_other_continues_to_brain():
    db = PostgresDB()
    sm = StateManager(RedisCache(), db)
    session_id = make_session(sm)
    sm.update_session(session_id, {"context": {"pending_quote_offer": True}})
    brain = DummyBrain(result=SimpleResult(reply="brain handled it"), decision="other")
    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm, brain=brain)

    out = await conv.process("actually, what is the weather", session_id, "1")

    assert out["response"] == "brain handled it"
    assert len(brain.converse_calls) == 1


@pytest.mark.asyncio
async def test_can_not_answer_brain_reply_keeps_reply_without_agent_offer():
    db = PostgresDB()
    sm = StateManager(RedisCache(), db)
    session_id = make_session(sm)
    brain = DummyBrain(
        result=SimpleResult(
            reply=(
                "I'm sorry, I can't answer that. Would you like me to connect you "
                "with an agent who can give you more information?"
            )
        )
    )
    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm, brain=brain)

    out = await conv.process("what is the minimum deposit for the balanced fund", session_id, "1")

    # The brain's own wording is preserved, but no agent handoff is armed: MIA
    # must answer confidently and never volunteer a human agent.
    assert out["response"].startswith("I'm sorry, I can't answer that.")
    assert out.get("show_handover_button") is False
    session = sm.get_session(session_id)
    assert not session["context"].get("pending_agent_offer")


@pytest.mark.asyncio
async def test_router_greeting_answers_directly_no_brain_no_rag():
    db = PostgresDB()
    sm = StateManager(RedisCache(), db)
    session_id = make_session(sm)
    router = DummyRouter(label="GREETING", reply="Hey there! How can I help you with Old Mutual today?")
    brain = DummyBrain(result=SimpleResult(reply="should not be used"))
    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm, brain=brain, intent_router=router)

    out = await conv.process("howzit", session_id, "1")

    assert out["response"] == "Hey there! How can I help you with Old Mutual today?"
    assert out["intent_type"] == "NO_RETRIEVAL"
    assert len(router.calls) == 1
    assert len(brain.converse_calls) == 0


@pytest.mark.asyncio
async def test_router_fast_path_greeting_uses_canned():
    db = PostgresDB()
    sm = StateManager(RedisCache(), db)
    session_id = make_session(sm)
    router = DummyRouter(label="GREETING", reply=None)
    brain = DummyBrain(result=SimpleResult(reply="should not be used"))
    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm, brain=brain, intent_router=router)

    out = await conv.process("yo", session_id, "1")

    assert "MIA" in out["response"]
    assert len(brain.converse_calls) == 0


@pytest.mark.asyncio
async def test_router_off_topic_reply():
    db = PostgresDB()
    sm = StateManager(RedisCache(), db)
    session_id = make_session(sm)
    router = DummyRouter(label="OFF_TOPIC", reply="I only help with Old Mutual products and services.")
    brain = DummyBrain(result=SimpleResult(reply="should not be used"))
    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm, brain=brain, intent_router=router)

    out = await conv.process("what is the weather", session_id, "1")

    assert out["response"] == "I only help with Old Mutual products and services."
    assert len(brain.converse_calls) == 0


@pytest.mark.asyncio
async def test_om_question_with_ungrounded_brain_forces_chunks():
    db = PostgresDB()
    sm = StateManager(RedisCache(), db)
    session_id = make_session(sm)
    router = DummyRouter(label="OM_QUESTION", reply=None)
    brain = DummyBrain(result=SimpleResult(reply="I remember serenicare covers dental.", used_knowledge=False))
    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm, brain=brain, intent_router=router)

    out = await conv.process("what does serenicare cover", session_id, "1")

    # The brain skipped the knowledge base, so the reply is regenerated strictly
    # from retrieved chunks (the DummyRAG tags its answer with "LEGACY:").
    assert out.get("grounded") is True
    assert "LEGACY" in out["response"]
    assert len(brain.converse_calls) == 1


@pytest.mark.asyncio
async def test_om_question_with_grounded_brain_accepted():
    db = PostgresDB()
    sm = StateManager(RedisCache(), db)
    session_id = make_session(sm)
    router = DummyRouter(label="OM_QUESTION", reply=None)
    brain = DummyBrain(result=SimpleResult(reply="Serenicare covers dental.", used_knowledge=True))
    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm, brain=brain, intent_router=router)

    out = await conv.process("what does serenicare cover", session_id, "1")

    assert out["response"] == "Serenicare covers dental."
    assert out.get("grounded") is not True


@pytest.mark.asyncio
async def test_router_skipped_while_pending_quote_offer():
    db = PostgresDB()
    sm = StateManager(RedisCache(), db)
    session_id = make_session(sm)
    sm.update_session(session_id, {"context": {"pending_quote_offer": True}})
    router = DummyRouter(label="GREETING", reply="greeting should be ignored")
    brain = DummyBrain(result=SimpleResult(reply="quote-confirmation handled"), decision="other")
    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm, brain=brain, intent_router=router)

    out = await conv.process("yes please", session_id, "1")

    # Pending state is resolved by the brain bridge, not the router.
    assert out["response"] == "quote-confirmation handled"
    assert len(router.calls) == 0
    assert len(brain.confirm_calls) == 1
    assert len(brain.converse_calls) == 1
