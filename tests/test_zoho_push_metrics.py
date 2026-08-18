import json
from datetime import datetime

import pytest

from src.database.postgres import PostgresDB
from src.integrations.zoho.push_metrics import impact_payload_to_crm_record, push_day

PAYLOAD = {
    "window": {"days": 1, "conversations": 10, "escalations": 2, "botDown": 1, "noVerdict": 1},
    "kpis": [
        {"key": "fallback_rate", "value": 10.0},
        {"key": "bot_down_rate", "value": 10.0},
    ],
    "resolution": {
        "strict": 85.71,
        "selfServe": 70.0,
        "resolved": 6,
        "unresolved": 1,
        "escalated": 2,
        "botDown": 1,
        "noVerdict": 1,
        "inProgress": 0,
        "verdictTotal": 7,
    },
    "csat": {"value": 4.5, "responses": 3},
    "latency": {"value": 3.2},
    "offHours": {"total": 4, "handled": 3, "rate": 75.0},
    "quoteToPayment": {"quotes": 5, "paid": 2, "rate": 40.0},
    "effortHoursSaved": {"hours": 1.5, "chats": 7},
    "repeatUsers": {"activeUsers": 8, "repeatUsers": 2, "repeatRate": 25.0},
}


def test_record_mapping_covers_all_crm_fields():
    record = impact_payload_to_crm_record(PAYLOAD, "2026-08-18")

    assert record == {
        "Metric_Date": "2026-08-18",
        "Conversations": 10,
        "Resolved": 6,
        "Escalated": 2,
        "Could_Not_Answer": 1,
        "Bot_Down": 1,
        "Resolution_Rate": 85.71,
        "Self_Serve_Rate": 70.0,
        "Fallback_Rate": 10.0,
        "Bot_Down_Rate": 10.0,
        "CSAT": 4.5,
        "Avg_Latency_Seconds": 3.2,
        "Off_Hours_Rate": 75.0,
        "Quote_to_Payment_Rate": 40.0,
        "Effort_Hours_Saved": 1.5,
        "Repeat_User_Rate": 25.0,
    }


def test_record_mapping_handles_empty_payload():
    record = impact_payload_to_crm_record({}, "2026-08-18")

    assert record["Metric_Date"] == "2026-08-18"
    assert record["Conversations"] == 0
    assert record["Resolution_Rate"] == 0.0


class FakeWriter:
    def __init__(self):
        self.module = "Mia_Bot_Metrics"
        self.upserts = []

    def upsert(self, records, duplicate_check_fields):
        self.upserts.append({"records": records, "duplicate_check_fields": duplicate_check_fields})
        return {"status": "success"}


def test_push_day_upserts_one_record_keyed_by_date():
    db = PostgresDB()
    writer = FakeWriter()

    result = push_day(db, day=datetime(2026, 8, 18, 12, 0), writer=writer)

    assert result["date"] == "2026-08-18"
    assert len(writer.upserts) == 1
    call = writer.upserts[0]
    assert call["duplicate_check_fields"] == ["Metric_Date"]
    assert len(call["records"]) == 1
    assert call["records"][0]["Metric_Date"] == "2026-08-18"
    assert result["record"] is call["records"][0]


def test_push_day_counts_only_that_day(monkeypatch):
    db = PostgresDB()
    user = db.get_or_create_user("256700000001")
    db.create_conversation(user_id=str(user.id), mode="conversational", created_at=datetime(2026, 8, 18, 9, 0))
    db.create_conversation(user_id=str(user.id), mode="conversational", created_at=datetime(2026, 8, 15, 9, 0))

    writer = FakeWriter()
    result = push_day(db, day=datetime(2026, 8, 18), writer=writer)

    assert result["record"]["Conversations"] == 1, "only the target day's conversations count"


def test_push_day_same_day_twice_is_one_upsert_each():
    db = PostgresDB()
    writer = FakeWriter()

    push_day(db, day=datetime(2026, 8, 18), writer=writer)
    push_day(db, day=datetime(2026, 8, 18), writer=writer)

    dates = [u["records"][0]["Metric_Date"] for u in writer.upserts]
    assert dates == ["2026-08-18", "2026-08-18"], "CRM upsert keyed by Metric_Date dedupes server-side"
