"""Tests for the greeting identity-capture flow.

A new user who greets the bot is asked for their email. The name is derived
from the email address; the email is stored on the user record for follow-up.
Capture must never block a real question.
"""

import pytest

from src.chatbot.modes.conversational import (
    CLIENT_NAME_MASK,
    IDENTITY_ASK_PROMPT,
    ConversationalMode,
    _derive_name_from_email,
    _extract_email,
    _extract_name,
    _looks_like_question,
    _time_greeting_eat,
)
from src.database.postgres import PostgresDB


class _FakeStateManager:
    def __init__(self, db):
        self.db = db
        self.sessions = {}

    def get_session(self, session_id):
        return self.sessions.get(session_id)

    def update_session(self, session_id, updates):
        session = self.sessions.setdefault(session_id, {})
        session.update(updates)


def _make_mode(db, session_id):
    sm = _FakeStateManager(db)
    sm.sessions[session_id] = {"context": {}}
    mode = object.__new__(ConversationalMode)
    mode.state_manager = sm
    return mode, sm


def test_extract_email():
    assert _extract_email("john.doe@example.com") == "john.doe@example.com"
    assert _extract_email("email me at A.B-1+2@sub.x.co.uk please") == "A.B-1+2@sub.x.co.uk"
    assert _extract_email("no email here") is None


def test_extract_name():
    assert _extract_name("My name is John", None) == "John"
    assert _extract_name("I am Jane Smith", None) == "Jane Smith"
    assert _extract_name("John Doe, john.doe@example.com", "john.doe@example.com") == "John Doe"
    assert _extract_name("my name is Jane and my email is jane@x.com", "jane@x.com") == "Jane"
    assert _extract_name("jane@x.com", "jane@x.com") is None


def test_looks_like_question():
    assert _looks_like_question("what is covered?") is True
    assert _looks_like_question("I need a quote") is True
    assert _looks_like_question("John Doe") is False
    assert _looks_like_question("") is False


def test_greeting_triggers_identity_ask():
    db = PostgresDB()
    user = db.get_or_create_user("+256700000001")
    mode, sm = _make_mode(db, "s1")

    resp = mode._maybe_handle_identity_capture(
        "hi", "s1", user.id, "conv1", sm.sessions["s1"], db, 0.0
    )

    assert resp is not None
    time_greeting = _time_greeting_eat()
    assert time_greeting in resp["response"]
    assert "email" in resp["response"].lower()
    assert resp["intent"] == "greeting"
    assert sm.sessions["s1"]["context"]["pending_identity_capture"] is True


def test_identity_capture_persists_name_and_email_masked():
    db = PostgresDB()
    user = db.get_or_create_user("+256700000002")
    mode, sm = _make_mode(db, "s1")

    mode._maybe_handle_identity_capture("hello", "s1", user.id, "conv1", sm.sessions["s1"], db, 0.0)
    resp = mode._maybe_handle_identity_capture(
        "john.doe@example.com", "s1", user.id, "conv1", sm.sessions["s1"], db, 0.0
    )

    assert resp is not None
    assert resp["intent"] == "identity_captured"
    stored = db.get_user_by_id(user.id)
    assert stored.email == "john.doe@example.com"
    assert stored.name == "John"  # derived from email local part
    assert stored.identity_captured_at is not None
    assert "pending_identity_capture" not in sm.sessions["s1"]["context"]

    events = db.get_conversation_events("conv1")
    captured = [e for e in events if e.event_type == "identity_captured"]
    assert captured, "expected identity_captured event"
    assert captured[0].payload["name_masked"] == CLIENT_NAME_MASK
    assert captured[0].payload["email"] == "john.doe@example.com"


def test_identity_capture_email_derives_name():
    db = PostgresDB()
    user = db.get_or_create_user("+256700000003")
    mode, sm = _make_mode(db, "s1")

    mode._maybe_handle_identity_capture("hi", "s1", user.id, "conv1", sm.sessions["s1"], db, 0.0)
    resp = mode._maybe_handle_identity_capture(
        "john@example.com", "s1", user.id, "conv1", sm.sessions["s1"], db, 0.0
    )

    assert resp is not None
    assert resp["intent"] == "identity_captured"
    stored = db.get_user_by_id(user.id)
    assert stored.email == "john@example.com"
    assert stored.name == "John"  # derived from email


def test_identity_capture_never_blocks_a_real_question():
    db = PostgresDB()
    user = db.get_or_create_user("+256700000004")
    mode, sm = _make_mode(db, "s1")

    mode._maybe_handle_identity_capture("hello", "s1", user.id, "conv1", sm.sessions["s1"], db, 0.0)
    resp = mode._maybe_handle_identity_capture(
        "what insurance products do you offer?", "s1", user.id, "conv1", sm.sessions["s1"], db, 0.0
    )

    assert resp is None  # normal processing continues
    assert "pending_identity_capture" not in sm.sessions["s1"]["context"]
    assert db.get_user_by_id(user.id).email is None


def test_identity_ask_skipped_once_email_known():
    db = PostgresDB()
    user = db.get_or_create_user("+256700000005")
    db.set_user_identity(user.id, name="Jane", email="jane@x.com")
    mode, sm = _make_mode(db, "s1")

    resp = mode._maybe_handle_identity_capture(
        "hi", "s1", user.id, "conv1", sm.sessions["s1"], db, 0.0
    )

    assert resp is not None  # personalized greeting for returning user
    assert resp["intent"] == "greeting_returning"
    assert "Jane" in resp["response"]