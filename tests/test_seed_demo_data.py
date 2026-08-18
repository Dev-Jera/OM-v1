import pytest

from datetime import datetime, timedelta

from src.database.postgres import PostgresDB
from src.scripts.seed_demo_data import seed_demo_data


@pytest.mark.asyncio
async def test_seeder_populates_metrics():
    db = PostgresDB()
    stats = seed_demo_data(db, days=30)

    assert stats["users"] == 40
    assert stats["conversations"] == 160
    assert stats["events"] > 0
    assert stats["metrics"] > 0

    now = datetime.utcnow()
    assert db.count_conversations(now - timedelta(days=30), now) == 160

    # Path events exist for every conversation.
    from datetime import datetime as dt

    paths = {
        e.conversation_id
        for e in db.list_conversation_events(
            start=dt.min, end=dt.max, event_type="conversation_path"
        )
    }
    assert len(paths) == 160

    # Impact KPIs should now show volume.
    from src.api.main import get_impact_metrics

    impact = await get_impact_metrics(days=30, db=db)
    assert impact["window"]["conversations"] == 160
    assert impact["window"]["escalations"] > 0
    assert any(kpi["key"] == "resolution_rate" for kpi in impact["kpis"])
    assert impact["repeatUsers"]["activeUsers"] > 0