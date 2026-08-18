import pytest

from src.chatbot.flows.router import ChatRouter
from src.chatbot.modes.conversational import ConversationalMode
from src.chatbot.state_manager import StateManager
from src.database.postgres import PostgresDB
from src.database.redis import RedisCache


class DummyRAG:
    async def retrieve(self, query, filters=None, top_k=None):
        return [{"payload": {"text": "stub"}}]

    async def generate(self, query, context_docs, conversation_history):
        return {"answer": "ANSWER: stub", "confidence": 0.5, "sources": [{"id": "1"}]}


class DummyMatcher:
    def match_products(self, query, top_k=3):
        return []


class DummyGuided:
    async def process(self, *args, **kwargs):
        raise AssertionError("guided.process should not be called")

    async def start_flow(self, *args, **kwargs):
        raise AssertionError("guided.start_flow should not be called")


def _events(db, event_type=None):
    from datetime import datetime

    events = db.list_conversation_events(start=datetime.min, end=datetime.max)
    if event_type:
        events = [e for e in events if e.event_type == event_type]
    return events


@pytest.mark.asyncio
async def test_connect_agent_button_records_escalation_confirmed_event():
    db = PostgresDB()
    redis = RedisCache()
    sm = StateManager(redis, db)
    user = db.get_or_create_user("256700000222")
    session_id = sm.create_session(str(user.id))
    session = sm.get_session(session_id)
    conversation_id = session["conversation_id"]

    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm)
    router = ChatRouter(conv, DummyGuided(), sm, DummyMatcher())

    out = await router.route("", session_id, str(user.id), form_data={"action": "connect_agent"})

    assert out["mode"] == "escalated"
    assert sm.get_escalation_state(session_id).get("escalated") is True
    events = _events(db, "escalation_confirmed")
    assert len(events) == 1
    assert events[0].conversation_id == conversation_id
    assert events[0].payload["source"] == "button"
    assert events[0].payload["reason"] == "customer_requested_agent"


@pytest.mark.asyncio
async def test_duplicate_escalation_events_dedupe_by_conversation():
    db = PostgresDB()
    redis = RedisCache()
    sm = StateManager(redis, db)
    user = db.get_or_create_user("256700000333")
    session_id = sm.create_session(str(user.id))

    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm)
    router = ChatRouter(conv, DummyGuided(), sm, DummyMatcher())

    # Two escalation paths for the SAME conversation must not double-count.
    await router.route("", session_id, str(user.id), form_data={"action": "connect_agent"})
    conversation_id = sm.get_session(session_id)["conversation_id"]
    db.add_conversation_event(
        conversation_id=conversation_id,
        event_type="escalation_confirmed",
        payload={"source": "user", "reason": "user_requested_agent"},
    )

    from datetime import datetime

    distinct = {
        e.conversation_id
        for e in db.list_conversation_events(
            start=datetime.min, end=datetime.max, event_type="escalation_confirmed"
        )
        if e.conversation_id
    }
    assert len(distinct) == 1


@pytest.mark.asyncio
async def test_direct_escalate_endpoint_emits_escalation_confirmed():
    """/escalate must emit escalation_confirmed so direct escalations count in
    the outcome model just like chat-flow escalations."""
    import src.api.escalation as escalation_module
    from src.api.escalation import EscalateRequest, escalate

    db = PostgresDB()
    redis = RedisCache()
    sm = StateManager(redis, db)
    escalation_module.state_manager = sm

    user = db.get_or_create_user("256700000444")
    session_id = sm.create_session(str(user.id))
    conversation_id = sm.get_session(session_id)["conversation_id"]

    result = await escalate(EscalateRequest(session_id=session_id, reason="customer_requested_agent"))

    assert result["success"] is True
    assert sm.get_escalation_state(session_id).get("escalated") is True
    events = _events(db, "escalation_confirmed")
    assert len(events) == 1
    assert events[0].conversation_id == conversation_id
    assert events[0].payload["reason"] == "customer_requested_agent"