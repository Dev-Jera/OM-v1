from datetime import datetime

import pytest

from src.database.postgres import PostgresDB
from src.integrations.zoho import escalation_push
from src.integrations.zoho.escalation_push import (
    build_escalation_record,
    push_escalation_to_zoho,
)


@pytest.fixture
def db_with_chat():
    db = PostgresDB()
    user = db.get_or_create_user("256700000002")
    db.set_user_identity(user_id=str(user.id), name="Nakato Grace")
    db.set_zoho_contact(user_id=str(user.id), zoho_contact_id="998877")
    conv = db.create_conversation(user_id=str(user.id), mode="conversational")
    db.add_message(conversation_id=str(conv.id), role="user", content="Hello, I need help")
    db.add_message(conversation_id=str(conv.id), role="assistant", content="Sure, how can I help?")
    db.add_message(conversation_id=str(conv.id), role="user", content="Talk to an agent")
    return db, user, conv


def test_gate_off_by_default(monkeypatch):
    monkeypatch.delenv("ZOHO_ESCALATION_PUSH_ENABLED", raising=False)
    assert push_escalation_to_zoho(session_id="s1", reason="r") is False


@pytest.mark.parametrize("flag", ["1", "true", "YES", "on"])
def test_gate_on(monkeypatch, flag):
    monkeypatch.setenv("ZOHO_ESCALATION_PUSH_ENABLED", flag)
    assert escalation_push._enabled() is True


def test_record_contains_customer_and_transcript(db_with_chat):
    db, user, conv = db_with_chat

    record = build_escalation_record(
        session_id="sess-1",
        reason="user_requested_agent",
        user_id=str(user.id),
        metadata={"conversation_id": str(conv.id)},
        db=db,
    )

    assert record["Session_ID"] == "sess-1"
    assert record["Conversation_ID"] == str(conv.id)
    assert record["Reason"] == "user_requested_agent"
    assert record["Customer_Name"] == "Nakato Grace"
    assert record["Phone"] == "256700000002"
    assert record["Zoho_Contact_Id"] == "998877"
    assert record["Status"] == "New"
    assert "user: Hello, I need help" in record["Transcript"]
    assert "assistant: Sure, how can I help?" in record["Transcript"]
    lines = record["Transcript"].splitlines()
    assert lines[0].startswith("user:"), "transcript is oldest-first"


def test_record_without_db_or_user():
    record = build_escalation_record(
        session_id="sess-2", reason="low_confidence", user_id=None, metadata=None, db=None
    )

    assert record["Customer_Name"] == ""
    assert record["Transcript"] == ""
    assert record["Conversation_ID"] == "sess-2", "falls back to session id"


def test_push_attempts_when_enabled_and_never_raises(monkeypatch, db_with_chat):
    db, user, conv = db_with_chat
    monkeypatch.setenv("ZOHO_ESCALATION_PUSH_ENABLED", "true")
    monkeypatch.setenv("ZOHO_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "csec")
    monkeypatch.setenv("ZOHO_REFRESH_TOKEN", "rt")

    pushed = []

    def fake_push_sync(record, module):
        pushed.append((record, module))
        raise RuntimeError("zoho down")

    monkeypatch.setattr(escalation_push, "_push_sync", fake_push_sync)
    monkeypatch.setenv("ZOHO_ESCALATION_MODULE", "Mia_Escalations")

    attempted = push_escalation_to_zoho(
        session_id="sess-3",
        reason="user_requested_agent",
        user_id=str(user.id),
        metadata={"conversation_id": str(conv.id)},
        db=db,
        background=False,
    )

    assert attempted is True
    assert len(pushed) == 1, "push attempted exactly once"
    assert pushed[0][1] == "Mia_Escalations"
    assert pushed[0][0]["Session_ID"] == "sess-3"


def test_push_skips_silently_without_credentials(monkeypatch, caplog):
    monkeypatch.setenv("ZOHO_ESCALATION_PUSH_ENABLED", "true")
    monkeypatch.delenv("ZOHO_CLIENT_ID", raising=False)
    monkeypatch.delenv("ZOHO_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("ZOHO_REFRESH_TOKEN", raising=False)

    attempted = push_escalation_to_zoho(session_id="s", reason="r", background=False)

    assert attempted is True, "gate open counts as an attempt; missing creds log and skip"


def test_service_hook_survives_push_module_failure(monkeypatch):
    from src.integrations.policy.escalation_service import EscalationService

    class FakeStateManager:
        def __init__(self):
            self.marked = []
            self.db = None

        def mark_escalated(self, session_id, reason=None, metadata=None):
            self.marked.append(session_id)

    def broken_push(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setenv("ZOHO_ESCALATION_PUSH_ENABLED", "true")
    monkeypatch.setattr(
        "src.integrations.zoho.escalation_push.push_escalation_to_zoho", broken_push
    )

    sm = FakeStateManager()
    record = EscalationService(state_manager=sm).escalate_to_human(
        session_id="sess-x", reason="test"
    )

    assert sm.marked == ["sess-x"], "escalation itself still succeeds"
    assert record["session_id"] == "sess-x"
