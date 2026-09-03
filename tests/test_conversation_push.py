"""Tests for the conversation push to Zoho CRM."""

import os
from unittest.mock import patch

from src.integrations.zoho.conversation_push import (
    build_conversation_record,
    _resolve_outcome,
    _resolve_csat,
    _resolve_message_count,
    _enabled,
)
from src.database.postgres import PostgresDB


class FakeConversation:
    def __init__(self, mode="conversational", created_at=None, ended_at=None):
        self.mode = mode
        self.created_at = created_at
        self.ended_at = ended_at


class FakeEvent:
    def __init__(self, event_type, payload=None):
        self.event_type = event_type
        self.payload = payload or {}


class FakeMessage:
    def __init__(self, role="user", content="hello"):
        self.role = role
        self.content = content


# ── _enabled ─────────────────────────────────────────────────────

def test_enabled_gate():
    with patch.dict(os.environ, {"ZOHO_CONVERSATION_PUSH_ENABLED": "true"}):
        assert _enabled() is True
    with patch.dict(os.environ, {"ZOHO_CONVERSATION_PUSH_ENABLED": ""}):
        assert _enabled() is False


# ── _resolve_outcome ─────────────────────────────────────────────

def test_resolve_outcome_bot_down():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    db.add_conversation_event(conversation_id=conv.id, event_type="service_error", payload={"error": "timeout"})
    assert _resolve_outcome(db, conv.id) == "bot_down"


def test_resolve_outcome_escalated():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    db.add_conversation_event(conversation_id=conv.id, event_type="escalation_confirmed", payload={"reason": "asked"})
    assert _resolve_outcome(db, conv.id) == "escalated"


def test_resolve_outcome_resolved():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    db.add_conversation_event(conversation_id=conv.id, event_type="completion_confirmed", payload={"outcome": "resolved"})
    assert _resolve_outcome(db, conv.id) == "resolved"


def test_resolve_outcome_unresolved():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    db.add_conversation_event(conversation_id=conv.id, event_type="completion_confirmed", payload={"outcome": "unresolved"})
    assert _resolve_outcome(db, conv.id) == "unresolved"


def test_resolve_outcome_no_verdict():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    assert _resolve_outcome(db, conv.id) == "no_verdict"


def test_resolve_outcome_priority_bot_down_over_resolved():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    db.add_conversation_event(conversation_id=conv.id, event_type="completion_confirmed", payload={"outcome": "resolved"})
    db.add_conversation_event(conversation_id=conv.id, event_type="service_error", payload={"error": "crash"})
    assert _resolve_outcome(db, conv.id) == "bot_down"


# ── _resolve_csat ────────────────────────────────────────────────

def test_resolve_csat_found():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    db.add_conversation_event(conversation_id=conv.id, event_type="csat", payload={"rating": 4})
    assert _resolve_csat(db, conv.id) == 4.0


def test_resolve_csat_not_found():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    assert _resolve_csat(db, conv.id) is None


# ── _resolve_message_count ───────────────────────────────────────

def test_resolve_message_count():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    for _ in range(5):
        db.add_message(conv.id, "user", "hi")
        db.add_message(conv.id, "assistant", "hello")
    count = _resolve_message_count(db, conv.id)
    assert count == 10


# ── build_conversation_record ────────────────────────────────────

def test_build_record_with_product_topic():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    ctx = {"product_topic": {"name": "Motor Private", "digital_flow": "motor_private"}}
    record = build_conversation_record(
        conversation_id=conv.id,
        user_id="u1",
        session_context=ctx,
        db=db,
        conversation=FakeConversation(),
    )
    assert record["Product_Name"] == "Motor Private"
    assert record["Product_Category"] == "vehicle"
    assert record["Conversation_ID"] == conv.id


def test_build_record_no_product():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    record = build_conversation_record(
        conversation_id=conv.id,
        user_id="u1",
        session_context={},
        db=db,
        conversation=FakeConversation(),
    )
    assert record["Product_Name"] == "none"
    assert record["Product_Category"] == "general"


def test_build_record_with_user():
    db = PostgresDB()
    user = db.get_or_create_user("256700111111")
    db.set_user_identity(user.id, name="Jane Doe")
    conv = db.create_conversation(user.id, "conversational")
    record = build_conversation_record(
        conversation_id=conv.id,
        user_id=user.id,
        session_context={},
        db=db,
        conversation=FakeConversation(),
    )
    assert record["Customer_Name"] == "Jane Doe"
    assert record["Phone"] == "256700111111"


def test_build_record_with_csat():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    db.add_conversation_event(conversation_id=conv.id, event_type="csat", payload={"rating": 5})
    record = build_conversation_record(
        conversation_id=conv.id,
        user_id="u1",
        session_context={},
        db=db,
        conversation=FakeConversation(),
    )
    assert record["CSAT"] == 5.0


def test_build_record_with_mode():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    record = build_conversation_record(
        conversation_id=conv.id,
        user_id="u1",
        session_context={},
        db=db,
        conversation=FakeConversation(mode="guided"),
    )
    assert record["Mode"] == "guided"


def test_build_record_empty_context():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    record = build_conversation_record(
        conversation_id=conv.id,
        user_id="u1",
        session_context=None,
        db=db,
        conversation=FakeConversation(),
    )
    assert record["Product_Name"] == "none"
    assert record["Outcome"] == "no_verdict"


def test_build_record_unmatched_interest():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    ctx = {"unmatched_interest": "health insurance"}
    record = build_conversation_record(
        conversation_id=conv.id,
        user_id="u1",
        session_context=ctx,
        db=db,
        conversation=FakeConversation(),
    )
    assert record["Unmatched_Interest"] == "health insurance"
    assert record["Product_Name"] == "none"


def test_build_record_unmatched_interest_empty_by_default():
    db = PostgresDB()
    conv = db.create_conversation("u1", "conversational")
    record = build_conversation_record(
        conversation_id=conv.id,
        user_id="u1",
        session_context={},
        db=db,
        conversation=FakeConversation(),
    )
    assert record["Unmatched_Interest"] == ""
