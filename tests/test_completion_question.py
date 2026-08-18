import pytest

from src.chatbot.modes.conversational import (
    COMPLETION_ASK_PROMPT,
    COMPLETION_RESOLVED_PROMPT,
    COMPLETION_UNRESOLVED_PROMPT,
    ConversationalMode,
)
from src.chatbot.state_manager import StateManager
from src.database.postgres import PostgresDB
from src.database.redis import RedisCache


class DummyRAG:
    async def retrieve(self, query, filters=None, top_k=None):
        return [{"payload": {"text": "stub"}}]

    async def generate(self, query, context_docs, conversation_history):
        return {"answer": "ANSWER: stub", "confidence": 0.5, "sources": [{"id": "1"}]}


class NoMatchMatcher:
    def match_products(self, query, top_k=3):
        return []


def _events(db, event_type=None):
    from datetime import datetime

    events = db.list_conversation_events(start=datetime.min, end=datetime.max)
    if event_type:
        events = [e for e in events if e.event_type == event_type]
    return events


def _metrics(db, metric_type):
    from datetime import datetime

    return [
        m
        for m in db.list_rag_metrics(start=datetime.min, end=datetime.max, metric_types=[metric_type])
    ]


def _make(db):
    redis = RedisCache()
    sm = StateManager(redis, db)
    user = db.get_or_create_user("256700000111")
    session_id = sm.create_session(str(user.id))
    conv = ConversationalMode(DummyRAG(), NoMatchMatcher(), sm)
    return conv, sm, user, session_id


@pytest.mark.asyncio
async def test_goodbye_asks_completion_question_once():
    db = PostgresDB()
    conv, sm, user, session_id = _make(db)

    out = await conv.process("bye", session_id, str(user.id))

    assert out["mode"] == "conversational"
    assert out["response"] == COMPLETION_ASK_PROMPT
    session = sm.get_session(session_id)
    assert session["context"].get("pending_completion_question") is True
    assert session["context"].get("completion_asked") is True
    assert _events(db, "completion_confirmed") == []

    again = await conv.process("bye", session_id, str(user.id))
    assert again["response"] != COMPLETION_ASK_PROMPT


@pytest.mark.asyncio
async def test_completion_yes_records_resolved_outcome():
    db = PostgresDB()
    conv, sm, user, session_id = _make(db)

    await conv.process("bye", session_id, str(user.id))
    out = await conv.process("yes", session_id, str(user.id))

    assert out["outcome"] == "resolved"
    assert out["response"] == COMPLETION_RESOLVED_PROMPT
    events = _events(db, "completion_confirmed")
    assert len(events) == 1
    assert events[0].payload["outcome"] == "resolved"
    metrics = _metrics(db, "completion_outcome")
    assert len(metrics) == 1
    assert metrics[0].value == 1.0
    assert sm.get_session(session_id) is None  # conversation ended cleanly
    assert _events(db, "session_end")


@pytest.mark.asyncio
async def test_completion_no_records_unresolved_and_arms_agent_offer():
    db = PostgresDB()
    conv, sm, user, session_id = _make(db)

    await conv.process("bye", session_id, str(user.id))
    out = await conv.process("no", session_id, str(user.id))

    assert out["outcome"] == "unresolved"
    assert out["response"] == COMPLETION_UNRESOLVED_PROMPT
    assert out.get("show_handover_button") is True
    events = _events(db, "completion_confirmed")
    assert len(events) == 1
    assert events[0].payload["outcome"] == "unresolved"
    metrics = _metrics(db, "completion_outcome")
    assert len(metrics) == 1
    assert metrics[0].value == 0.0
    session = sm.get_session(session_id)
    assert session["context"].get("pending_agent_offer") is True


@pytest.mark.asyncio
async def test_completion_other_reply_continues_conversation():
    db = PostgresDB()
    conv, sm, user, session_id = _make(db)

    await conv.process("bye", session_id, str(user.id))
    out = await conv.process("what about motor insurance?", session_id, str(user.id))

    assert out.get("outcome") is None
    assert _events(db, "completion_confirmed") == []
    session = sm.get_session(session_id)
    assert not session["context"].get("pending_completion_question")


@pytest.mark.asyncio
async def test_completion_question_not_asked_without_goodbye():
    db = PostgresDB()
    conv, sm, user, session_id = _make(db)

    out = await conv.process("thanks", session_id, str(user.id))

    assert out["response"] != COMPLETION_ASK_PROMPT
    session = sm.get_session(session_id)
    assert not session["context"].get("pending_completion_question")
