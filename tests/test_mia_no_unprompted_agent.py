import pytest

from src.chatbot.brain import SYSTEM_INSTRUCTION as BRAIN_INSTRUCTION
from src.chatbot.modes.conversational import ConversationalMode
from src.chatbot.state_manager import StateManager
from src.database.postgres import PostgresDB
from src.database.redis import RedisCache
from src.rag.generate import SYSTEM_INSTRUCTION as GENERATE_INSTRUCTION


# --- Prompt regression guards ------------------------------------------------


def test_generate_prompt_never_volunteers_a_human_agent():
    assert "NEVER OFFER A HUMAN AGENT UNPROMPTED" in GENERATE_INSTRUCTION
    assert "Only answer from the Retrieved Data" in GENERATE_INSTRUCTION
    for old_offer in (
        "connect you with an agent",
        "Would you like me to connect you",
        "connect them with a human agent",
        "arrange for a human agent",
    ):
        assert old_offer not in GENERATE_INSTRUCTION


def test_brain_prompt_never_volunteers_a_human_agent():
    assert "HUMAN AGENT:" in BRAIN_INSTRUCTION
    assert "NEVER suggest, offer, or volunteer" in BRAIN_INSTRUCTION
    for old_offer in (
        "connect you with an agent",
        "Would you like me to connect you",
        "arrange for a human agent",
    ):
        assert old_offer not in BRAIN_INSTRUCTION


# --- Behavioural guards ------------------------------------------------------


class BombRAG:
    """RAG that must never be invoked: an explicit agent request short-circuits."""

    async def retrieve(self, query, filters=None, top_k=None):
        raise AssertionError("retrieve should not be called for an agent request")

    async def generate(self, query, context_docs, conversation_history):
        raise AssertionError("generate should not be called for an agent request")


class EmptyRAG:
    """Benign no-chunk RAG that records calls for non-escalating messages."""

    def __init__(self):
        self.retrieve_calls = []

    async def retrieve(self, query, filters=None, top_k=None):
        self.retrieve_calls.append(query)
        return []

    async def generate(self, query, context_docs, conversation_history):
        return {"answer": "I'll help with that.", "confidence": 0.4, "sources": []}


class LowConfidenceRAG:
    """Sources retrieved but the answer is low-confidence (was the offer_human path)."""

    async def retrieve(self, query, filters=None, top_k=None):
        return [{"payload": {"text": "stub chunk"}}]

    async def generate(self, query, context_docs, conversation_history):
        return {
            "answer": "I'm not sure about that.",
            "confidence": 0.15,
            "sources": [{"id": "chunk-1"}],
        }


class NoMatchMatcher:
    def match_products(self, query, top_k=3):
        return []


def _events(db, event_type=None):
    from datetime import datetime

    events = db.list_conversation_events(start=datetime.min, end=datetime.max)
    if event_type:
        events = [e for e in events if e.event_type == event_type]
    return events


def _make(db, rag):
    redis = RedisCache()
    sm = StateManager(redis, db)
    user = db.get_or_create_user("256700000002")
    session_id = sm.create_session(str(user.id))
    conv = ConversationalMode(rag, NoMatchMatcher(), sm)
    return conv, sm, user, session_id


@pytest.mark.asyncio
async def test_explicit_agent_request_escalates():
    db = PostgresDB()
    conv, sm, user, session_id = _make(db, BombRAG())

    out = await conv.process("I want to talk to an agent please", session_id, str(user.id))

    assert out["mode"] == "escalated"
    assert out.get("escalated") is True
    events = _events(db, "escalation_confirmed")
    assert len(events) == 1
    assert events[0].payload["source"] == "user"
    assert events[0].payload["reason"] == "user_requested_agent"


@pytest.mark.asyncio
async def test_speak_to_a_human_escalates():
    db = PostgresDB()
    conv, sm, user, session_id = _make(db, BombRAG())

    out = await conv.process("Can I speak to a human?", session_id, str(user.id))

    assert out["mode"] == "escalated"
    assert _events(db, "escalation_confirmed")


@pytest.mark.asyncio
async def test_explicit_refusal_to_see_agent_does_not_escalate():
    db = PostgresDB()
    rag = EmptyRAG()
    conv, sm, user, session_id = _make(db, rag)

    out = await conv.process("No thanks, I don't want to talk to an agent", session_id, str(user.id))

    assert out.get("escalated") is not True
    assert _events(db, "escalation_confirmed") == []
    assert rag.retrieve_calls, "normal chat flow must continue for non-requests"


@pytest.mark.asyncio
async def test_agent_complaint_does_not_escalate():
    db = PostgresDB()
    rag = EmptyRAG()
    conv, sm, user, session_id = _make(db, rag)

    out = await conv.process("why do you keep referring me to an agent? can't you reply?", session_id, str(user.id))

    assert out.get("escalated") is not True
    assert _events(db, "escalation_confirmed") == []
    assert rag.retrieve_calls, "normal chat flow must continue for complaints"


@pytest.mark.asyncio
async def test_low_confidence_with_sources_does_not_arm_agent_offer():
    db = PostgresDB()
    conv, sm, user, session_id = _make(db, LowConfidenceRAG())

    out = await conv.process("what happens if my flight is delayed", session_id, str(user.id))

    assert out.get("show_handover_button") is False
    session = sm.get_session(session_id)
    assert not session["context"].get("pending_agent_offer")
    events = _events(db, "unanswered_question")
    assert len(events) == 1
    assert events[0].payload["reason"] == "low_confidence"
