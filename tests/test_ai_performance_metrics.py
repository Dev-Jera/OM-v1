import pytest

from datetime import datetime, timedelta

from src.api.main import get_ai_performance_metrics
from src.database.postgres import PostgresDB


@pytest.mark.asyncio
async def test_ai_performance_path_breakdown_and_agent_timing():
    db = PostgresDB()
    now = datetime.utcnow()

    # Path events: 2 freeform, 1 direct_agent, 1 guided_flow.
    for path in ["freeform", "freeform", "direct_agent", "guided_flow"]:
        cid = f"conv-{path}-{abs(hash((path, len(db._conversation_events))))}"
        db.add_conversation_event(
            conversation_id=cid,
            event_type="conversation_path",
            payload={"path": path},
            created_at=now - timedelta(hours=1),
        )

    # One escalation where the agent joined 60s after the customer asked.
    escal_cid = "conv-escalation-1"
    db.add_conversation_event(
        conversation_id=escal_cid,
        event_type="escalation_confirmed",
        payload={"source": "button"},
        created_at=now - timedelta(minutes=10),
    )
    db.add_conversation_event(
        conversation_id=escal_cid,
        event_type="agent_joined",
        payload={"agent_id": "a1"},
        created_at=now - timedelta(minutes=10) + timedelta(seconds=60),
    )

    # Bot latency: one response_latency metric of 2.5s.
    db.add_rag_metric(
        metric_type="response_latency",
        value=2.5,
        conversation_id=escal_cid,
        created_at=now - timedelta(minutes=9),
    )

    result = await get_ai_performance_metrics(days=30, db=db)

    pb = result["pathBreakdown"]
    assert pb["total"] == 4
    assert pb["guided_flow"] == 1
    assert pb["direct_agent"] == 1
    assert pb["freeform"] == 2
    assert pb["percentages"]["freeform"] == 50.0

    at = result["agentTiming"]
    assert at["cases"] == 1
    assert at["avgTimeToAgentJoinSec"] == 60.0
    assert at["escalations"] == 1

    bl = result["botLatency"]
    assert bl["avgResponseMs"] == 2500
    assert bl["avgResponseSec"] == 2.5