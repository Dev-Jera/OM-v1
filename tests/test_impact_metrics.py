import pytest

from datetime import datetime, timedelta

from src.api.main import get_impact_metrics
from src.database.postgres import PostgresDB


@pytest.mark.asyncio
async def test_impact_metrics_kpi_suite():
    db = PostgresDB()
    now = datetime.utcnow()

    user_a = db.get_or_create_user("256700000611")
    user_b = db.get_or_create_user("256700000622")

    # Two conversations for user_a (repeat user), one for user_b.
    conv_ids = []
    for _ in range(2):
        c = db.create_conversation(user_id=str(user_a.id), mode="conversational")
        c.created_at = now - timedelta(hours=2)
        conv_ids.append(c.id)
    c = db.create_conversation(user_id=str(user_b.id), mode="conversational")
    c.created_at = now - timedelta(hours=2)
    conv_ids.append(c.id)

    # Off-hours conversation: yesterday 22:00 UTC => 01:00 Kampala (UTC+3), off-hours.
    off_hours_conv = db.create_conversation(user_id=str(user_b.id), mode="conversational")
    off_start = (now - timedelta(days=1)).replace(hour=22, minute=0, second=0, microsecond=0)
    off_hours_conv.created_at = off_start
    db.add_conversation_event(
        conversation_id=off_hours_conv.id,
        event_type="chat_request",
        payload={},
        created_at=off_start,
    )

    # One escalation confirmed for a conversation.
    db.add_conversation_event(
        conversation_id=conv_ids[0],
        event_type="escalation_confirmed",
        payload={"source": "button"},
        created_at=now - timedelta(hours=1),
    )

    # CSAT rating of 4.
    db.add_conversation_event(
        conversation_id=conv_ids[1],
        event_type="csat",
        payload={"rating": 4},
        created_at=now - timedelta(hours=1),
    )

    # Completion outcome: resolved for one conversation (event + metric).
    db.add_conversation_event(
        conversation_id=conv_ids[1],
        event_type="completion_confirmed",
        payload={"outcome": 1.0},
        created_at=now - timedelta(minutes=5),
    )
    db.add_rag_metric(
        metric_type="completion_outcome",
        value=1.0,
        conversation_id=conv_ids[1],
        created_at=now - timedelta(minutes=5),
    )
    # Latency metric 3.0s.
    db.add_rag_metric(
        metric_type="response_latency",
        value=3.0,
        conversation_id=conv_ids[1],
        created_at=now - timedelta(minutes=5),
    )
    # One conversation the bot could not answer (unresolved).
    db.add_conversation_event(
        conversation_id=conv_ids[2],
        event_type="unanswered_question",
        payload={"reason": "no_chunks"},
        created_at=now - timedelta(minutes=5),
    )
    db.add_rag_metric(
        metric_type="fallbacks",
        value=1.0,
        conversation_id=conv_ids[2],
        created_at=now - timedelta(minutes=5),
    )

    # One quote and one paid transaction.
    quote = db.create_quote(user_id=str(user_a.id), product_id="motor", premium_amount=100000)
    quote.generated_at = now - timedelta(hours=1)
    txn = db.create_payment_transaction(
        reference="PAY-1",
        provider="mtn",
        provider_reference="ref-1",
        phone_number="256700000611",
        amount=100000,
        currency="UGX",
        status="SUCCESS",
    )
    txn.created_at = now - timedelta(hours=1)

    result = await get_impact_metrics(days=30, db=db)

    assert result["window"]["conversations"] == 4
    kpis = {k["key"]: k for k in result["kpis"]}
    # Strict resolution: 1 resolved out of a 3-verdict pool (resolved + escalated + unresolved).
    assert kpis["resolution_rate"]["value"] == 33.33
    # Self-serve: 4 total - 1 escalated - 0 bot-down = 3 (75%).
    assert kpis["self_serve_rate"]["value"] == 75.0
    # Could-not-answer: 1 unresolved out of 4 conversations.
    assert kpis["fallback_rate"]["value"] == 25.0
    assert kpis["csat"]["value"] == 4.0
    assert kpis["latency_seconds"]["value"] == 3.0
    assert kpis["quote_to_payment_rate"]["value"] == 100.0
    assert result["csat"]["resolved"] == 4.0
    assert result["resolution"]["strict"] == 33.33
    assert result["resolution"]["selfServe"] == 75.0
    assert result["resolution"]["noVerdict"] == 0
    assert result["resolution"]["inProgress"] == 1
    assert result["effortHoursSaved"]["basis"] == "estimated"
    assert result["effortHoursSaved"]["chats"] == 3
    assert result["repeatUsers"]["activeUsers"] == 2
    assert result["repeatUsers"]["repeatUsers"] == 2
    assert result["offHours"]["total"] == 1
    assert result["offHours"]["handled"] == 1
    assert result["effortHoursSaved"]["hours"] > 0
    assert result["targets"]["resolution_rate"] == 80.0