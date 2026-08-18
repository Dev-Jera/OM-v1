import pytest

from src.chatbot.modes.conversational import ConversationalMode
from src.chatbot.state_manager import StateManager
from src.database.postgres import PostgresDB
from src.database.redis import RedisCache
from src.rag.generate import ERROR_RETRY_MESSAGE, classify_generation_error


class NoHitsRAG:
    """RAG that finds no chunks and returns a can't-answer reply with an agent offer."""

    async def retrieve(self, query, filters=None, top_k=None):
        return []

    async def generate(self, query, context_docs, conversation_history):
        return {
            "answer": (
                "I'm sorry, I can't answer that. Would you like me to connect you "
                "with an agent who can give you more information?"
            ),
            "confidence": 0.05,
            "sources": [],
            "offer_human": True,
        }


class OfferHumanWithSourcesRAG:
    """LLM said it can't answer even though chunks were retrieved."""

    async def retrieve(self, query, filters=None, top_k=None):
        return [{"payload": {"text": "stub chunk"}}]

    async def generate(self, query, context_docs, conversation_history):
        return {
            "answer": "I'm not sure about that. Let me connect you with an agent.",
            "confidence": 0.15,
            "sources": [{"id": "chunk-1"}],
            "offer_human": True,
        }


class ErrorRAG:
    """System failure: the generator is DOWN."""

    async def retrieve(self, query, filters=None, top_k=None):
        return []

    async def generate(self, query, context_docs, conversation_history):
        return {
            "answer": ERROR_RETRY_MESSAGE,
            "confidence": 0.0,
            "sources": [],
            "error": True,
            "error_kind": "quota",
        }


class AnsweredRAG:
    """Normal answered turn with retrieved chunks."""

    async def retrieve(self, query, filters=None, top_k=None):
        return [{"payload": {"text": "stub chunk"}}]

    async def generate(self, query, context_docs, conversation_history):
        return {
            "answer": "Travel insurance covers trips abroad.",
            "confidence": 0.7,
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


def _metrics(db, metric_type):
    from datetime import datetime

    return [
        m
        for m in db.list_rag_metrics(start=datetime.min, end=datetime.max, metric_types=[metric_type])
    ]


def _make_mode(db, rag, session_id="s1"):
    redis = RedisCache()
    sm = StateManager(redis, db)
    user = db.get_or_create_user("256700000001")
    sm.create_session(str(user.id))
    conv = ConversationalMode(rag, NoMatchMatcher(), sm)
    return conv, sm, user, session_id


@pytest.mark.asyncio
async def test_no_chunks_records_unanswered_event_and_metric():
    db = PostgresDB()
    conv, sm, user, session_id = _make_mode(db, NoHitsRAG())

    out = await conv.process("what is the minimum deposit for the balanced fund", session_id, str(user.id))

    assert out.get("show_handover_button") is True
    events = _events(db, "unanswered_question")
    assert len(events) == 1
    assert events[0].payload["reason"] == "no_chunks"
    assert events[0].payload["question"] == "what is the minimum deposit for the balanced fund"
    metrics = _metrics(db, "unanswered_questions")
    assert len(metrics) == 1
    assert metrics[0].value == 1.0
    assert _events(db, "service_error") == []


@pytest.mark.asyncio
async def test_system_error_records_service_error_and_not_unanswered():
    db = PostgresDB()
    conv, sm, user, session_id = _make_mode(db, ErrorRAG())

    out = await conv.process("what is the minimum deposit for the balanced fund", session_id, str(user.id))

    assert out.get("show_handover_button") is False
    events = _events(db, "service_error")
    assert len(events) == 1
    assert events[0].payload["error_kind"] == "quota"
    assert events[0].payload["question"] == "what is the minimum deposit for the balanced fund"
    metrics = _metrics(db, "service_errors")
    assert len(metrics) == 1
    assert metrics[0].value == 1.0
    assert _events(db, "unanswered_question") == []


@pytest.mark.asyncio
async def test_offer_human_with_sources_records_low_confidence_unanswered():
    db = PostgresDB()
    conv, sm, user, session_id = _make_mode(db, OfferHumanWithSourcesRAG())

    await conv.process("what happens if my flight is delayed", session_id, str(user.id))

    events = _events(db, "unanswered_question")
    assert len(events) == 1
    assert events[0].payload["reason"] == "low_confidence"
    assert _events(db, "service_error") == []


@pytest.mark.asyncio
async def test_answered_question_records_no_unanswered_or_service_error():
    db = PostgresDB()
    conv, sm, user, session_id = _make_mode(db, AnsweredRAG())

    await conv.process("what does travel insurance cover", session_id, str(user.id))

    assert _events(db, "unanswered_question") == []
    assert _events(db, "service_error") == []


def test_classify_generation_error_buckets():
    class ResourceExhausted(Exception):
        pass

    class ReadTimeout(Exception):
        pass

    class Generic(Exception):
        pass

    assert classify_generation_error(ResourceExhausted("quota exceeded")) == "quota"
    assert classify_generation_error(ResourceExhausted("HTTP 429")) == "quota"
    assert classify_generation_error(Generic("rate limit exceeded")) == "quota"
    assert classify_generation_error(ReadTimeout("timed out")) == "timeout"
    assert classify_generation_error(Generic("connection reset")) == "exception"
