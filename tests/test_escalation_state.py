import pytest

from src.chatbot.modes.conversational import ConversationalMode
from src.chatbot.state_manager import StateManager
from src.database.postgres import PostgresDB
from src.database.redis import RedisCache


class DummyRAG:
    async def retrieve(self, query: str, filters=None, top_k=None):
        return []

    async def generate(self, query: str, context_docs, conversation_history):
        return {"answer": "ok", "confidence": 0.9, "sources": []}


class DummyMatcher:
    def match_products(self, query: str, top_k: int = 3):
        return []


@pytest.mark.asyncio
async def test_escalation_persists_and_agent_join_updates_state():
    db = PostgresDB()
    redis = RedisCache()
    sm = StateManager(redis, db)

    user = db.get_or_create_user(phone_number="256700111111")
    session_id = sm.create_session(str(user.id))

    s1 = sm.mark_escalated(session_id, reason="customer_requested")
    assert s1.get("escalated") is True
    assert s1.get("escalation_reason") == "customer_requested"

    persisted = db.get_escalation_state(session_id)
    assert persisted is not None
    assert persisted.get("escalated") is True

    s2 = sm.mark_agent_joined(session_id, "agent-42")
    assert s2.get("escalated") is True
    assert s2.get("agent_id") == "agent-42"

    persisted2 = db.get_escalation_state(session_id)
    assert persisted2 is not None
    assert persisted2.get("agent_id") == "agent-42"

    s3 = sm.end_escalation(session_id)
    assert s3.get("escalated") is False
    assert s3.get("agent_id") is None


@pytest.mark.asyncio
async def test_conversational_mode_honors_persisted_escalation_state():
    db = PostgresDB()
    redis = RedisCache()
    sm = StateManager(redis, db)

    user = db.get_or_create_user(phone_number="256700222222")
    session_id = sm.create_session(str(user.id))

    sm.mark_escalated(session_id, reason="low_confidence")
    sm.mark_agent_joined(session_id, "agent-9")

    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm)
    out = await conv.process("hello", session_id, str(user.id))

    assert out.get("mode") == "escalated"
    assert out.get("escalated") is True
    assert out.get("agent_id") == "agent-9"
