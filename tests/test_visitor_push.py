import os

import pytest

from src.database.postgres import PostgresDB
from src.integrations.zoho.visitor_push import (
    VISITOR_NAME_MASK,
    build_visitor_name,
    build_visitor_record,
    push_visitor_to_zoho,
)


class _FakeUser:
    def __init__(self, email=None, phone=None):
        self.email = email
        self.phone_number = phone


class _FakeDB(PostgresDB):
    """Concrete subclass of the in-memory PostgresDB used in tests."""

    def __init__(self, user=None):
        super().__init__()
        self._fake_user = user

    def get_user_by_id(self, user_id):
        return self._fake_user

    def add_conversation_event(self, *a, **k):
        pass


@pytest.fixture(autouse=True)
def _reset_gate():
    saved = os.environ.get("ZOHO_VISITOR_PUSH_ENABLED")
    os.environ["ZOHO_VISITOR_PUSH_ENABLED"] = "true"
    yield
    if saved is None:
        os.environ.pop("ZOHO_VISITOR_PUSH_ENABLED", None)
    else:
        os.environ["ZOHO_VISITOR_PUSH_ENABLED"] = saved


def test_build_visitor_record_masks_real_name():
    rec = build_visitor_record(
        user_id="u1",
        email="john@example.com",
        phone="+256700000000",
        name="John Doe",
        source="chat",
    )
    assert rec is not None
    # The real name must NEVER appear in the record.
    assert "John" not in str(rec)
    assert "Doe" not in str(rec)
    # Only the masked placeholder is used for the name.
    assert rec["Email"] == "john@example.com"
    assert rec["Phone"] == "+256700000000"
    assert rec["Source"] == "chat"
    assert rec["Name"].startswith(VISITOR_NAME_MASK)
    assert rec["User_ID"] == "u1"


def test_build_visitor_record_records_anonymous_without_email_or_phone():
    rec = build_visitor_record(user_id="u1", email=None, phone=None)
    assert rec is not None
    # Anonymous visitors are recorded so visitor volume shows in dashboards.
    assert rec["Email"] == ""
    assert rec["Phone"] == ""
    assert rec["User_ID"] == "u1"
    assert rec["Source"] == "chat"
    assert rec["Name"].startswith(VISITOR_NAME_MASK)


def test_build_visitor_name_is_stable_for_same_email():
    name1 = build_visitor_name("john@example.com")
    name2 = build_visitor_name("john@example.com")
    assert name1 == name2
    assert name1.startswith(VISITOR_NAME_MASK)


def test_build_visitor_record_pulls_identity_from_db():
    db = _FakeDB(user=_FakeUser(email="jane@example.com", phone="+256700111111"))
    rec = build_visitor_record(user_id="u2", email=None, source="identify", db=db)
    assert rec is not None
    assert rec["Email"] == "jane@example.com"
    assert rec["Phone"] == "+256700111111"


def test_push_disabled_gate_returns_false():
    os.environ["ZOHO_VISITOR_PUSH_ENABLED"] = "false"
    assert push_visitor_to_zoho(user_id="u1", email="a@b.com") is False


def test_push_anonymous_returns_true():
    # Anonymous visitors (no email/phone) are now recorded; a push is attempted.
    assert push_visitor_to_zoho(user_id="u1", email=None, phone=None) is True
