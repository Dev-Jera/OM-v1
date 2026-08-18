"""Phase D: outcome-model consistency, mutual exclusivity and edge cases."""

import pytest

from datetime import datetime, timedelta

from src.database.postgres import PostgresDB
from src.metrics_outcomes import compute_conversation_outcomes


def _seed_conversation(db: PostgresDB, when: datetime) -> str:
    conv = db.create_conversation(user_id="u-seed", mode="conversational", created_at=when)
    db.add_conversation_event(
        conversation_id=conv.id,
        event_type="chat_request",
        payload={},
        created_at=when,
    )
    return conv.id


def _event(db: PostgresDB, cid: str, event_type: str, when: datetime, payload=None):
    db.add_conversation_event(
        conversation_id=cid,
        event_type=event_type,
        payload=payload or {},
        created_at=when,
    )


@pytest.mark.asyncio
async def test_outcomes_are_mutually_exclusive_and_cover_all():
    db = PostgresDB()
    now = datetime.utcnow()
    start = now - timedelta(hours=3)

    # A conversation with BOTH resolved and escalated signals -> escalated.
    c1 = _seed_conversation(db, start)
    _event(db, c1, "completion_confirmed", start + timedelta(minutes=1), {"outcome": 1.0})
    _event(db, c1, "escalation_confirmed", start + timedelta(minutes=2), {})

    # service_error AND escalation -> bot_down (bot being down wins).
    c2 = _seed_conversation(db, start)
    _event(db, c2, "service_error", start + timedelta(minutes=1), {})
    _event(db, c2, "escalation_confirmed", start + timedelta(minutes=2), {})

    # unresolved only.
    c3 = _seed_conversation(db, start)
    _event(db, c3, "unanswered_question", start + timedelta(minutes=1), {"reason": "no_chunks"})

    # resolved only.
    c4 = _seed_conversation(db, start)
    _event(db, c4, "completion_confirmed", start + timedelta(minutes=1), {"outcome": 1.0})

    # completed-no only.
    c5 = _seed_conversation(db, start)
    _event(db, c5, "completion_confirmed", start + timedelta(minutes=1), {"outcome": 0.0})

    # session ended with no verdict.
    c6 = _seed_conversation(db, start)
    _event(db, c6, "session_end", start + timedelta(minutes=1), {})

    # started but no terminal signal.
    c7 = _seed_conversation(db, start)

    outcomes = compute_conversation_outcomes(db, start, now)

    assert outcomes["total"] == 7
    assert outcomes["by_outcome"] == {
        "escalated": 1,
        "bot_down": 1,
        "unresolved": 2,
        "resolved": 1,
        "no_verdict": 1,
        "in_progress": 1,
    }
    assert outcomes["detail"][c1] == "escalated"
    assert outcomes["detail"][c2] == "bot_down"
    assert outcomes["detail"][c3] == "unresolved"
    assert outcomes["detail"][c4] == "resolved"
    assert outcomes["detail"][c5] == "unresolved"
    assert outcomes["detail"][c6] == "no_verdict"
    assert outcomes["detail"][c7] == "in_progress"

    # Sum of buckets == total (every conversation counted exactly once).
    assert sum(outcomes["by_outcome"].values()) == outcomes["total"]


@pytest.mark.asyncio
async def test_impact_uses_same_numbers_as_shared_model():
    db = PostgresDB()
    now = datetime.utcnow()
    start = now - timedelta(hours=3)

    cids = []
    for _ in range(10):
        c = db.create_conversation(user_id="u-consistency", mode="conversational", created_at=start)
        cids.append(c.id)
    # 6 resolved, 2 escalated, 1 bot_down, 1 unresolved.
    for i in range(6):
        _event(db, cids[i], "completion_confirmed", start + timedelta(seconds=i + 1), {"outcome": 1.0})
    for i in (6, 7):
        _event(db, cids[i], "escalation_confirmed", start + timedelta(seconds=i + 1), {})
    _event(db, cids[8], "service_error", start + timedelta(seconds=9), {})
    _event(db, cids[9], "unanswered_question", start + timedelta(seconds=10), {"reason": "low_confidence"})

    from src.api.main import get_impact_metrics, get_system_performance_metrics

    outcomes = compute_conversation_outcomes(db, start, now)
    impact = await get_impact_metrics(days=30, db=db)
    system = await get_system_performance_metrics(days=30, db=db)

    kpis = {k["key"]: k for k in impact["kpis"]}

    # Impact resolution == shared model (1 resolved per verdict).
    assert kpis["resolution_rate"]["value"] == round(outcomes["resolved"] / outcomes["verdict_total"] * 100, 2)
    # System-performance resolution == the same number.
    system_res = next(k for k in system["kpis"] if k["label"] == "AI Resolution Rate")
    assert float(system_res["value"].rstrip("%")) == kpis["resolution_rate"]["value"]
    # Escalation count matches everywhere.
    assert impact["window"]["escalations"] == outcomes["escalated"]


@pytest.mark.asyncio
async def test_outcomes_accept_worded_completion_outcomes():
    """The chat completion path writes "resolved"/"unresolved" strings; the
    outcome model must not silently treat those as unresolved."""
    db = PostgresDB()
    now = datetime.utcnow()
    start = now - timedelta(hours=3)

    c1 = _seed_conversation(db, start)
    _event(db, c1, "completion_confirmed", start + timedelta(minutes=1), {"outcome": "resolved"})
    c2 = _seed_conversation(db, start)
    _event(db, c2, "completion_confirmed", start + timedelta(minutes=1), {"outcome": "unresolved"})

    outcomes = compute_conversation_outcomes(db, start, now)

    assert outcomes["detail"][c1] == "resolved"
    assert outcomes["detail"][c2] == "unresolved"
    assert outcomes["resolved"] == 1
    assert outcomes["unresolved"] == 1


@pytest.mark.asyncio
async def test_outcomes_accept_mixed_numeric_and_worded():
    db = PostgresDB()
    now = datetime.utcnow()
    start = now - timedelta(hours=3)

    # Numeric (seeder) and worded (chat path) resolved signals both count.
    c1 = _seed_conversation(db, start)
    _event(db, c1, "completion_confirmed", start + timedelta(minutes=1), {"outcome": 1.0})
    c2 = _seed_conversation(db, start)
    _event(db, c2, "completion_confirmed", start + timedelta(minutes=1), {"outcome": "resolved"})

    outcomes = compute_conversation_outcomes(db, start, now)
    assert outcomes["resolved"] == 2
    assert outcomes["unresolved"] == 0


@pytest.mark.asyncio
async def test_orphan_csat_rating_is_excluded():
    db = PostgresDB()
    now = datetime.utcnow()
    start = now - timedelta(hours=3)

    cid = _seed_conversation(db, start)
    _event(db, cid, "completion_confirmed", start + timedelta(minutes=1), {"outcome": 1.0})
    _event(db, cid, "csat", start + timedelta(minutes=2), {"rating": 5})

    # Orphan rating: event in window but conversation not in the table.
    _event(db, "ghost-conversation", "csat", start + timedelta(minutes=3), {"rating": 1})

    from src.api.main import get_impact_metrics

    impact = await get_impact_metrics(days=30, db=db)
    assert impact["csat"]["value"] == 5.0
    assert impact["csat"]["responses"] == 1


@pytest.mark.asyncio
async def test_repeat_users_use_zoho_contact_identity_when_linked():
    db = PostgresDB()
    now = datetime.utcnow()
    start = now - timedelta(hours=3)

    # Two people with different phones, but Zoho says it is the same human.
    user_a = db.get_or_create_user("256700000701")
    user_b = db.get_or_create_user("256700000702")
    db.set_zoho_contact(str(user_a.id), "ZOHO-SHARED-1")
    db.set_zoho_contact(str(user_b.id), "ZOHO-SHARED-1")

    for user in (user_a, user_b):
        conv = db.create_conversation(user_id=str(user.id), mode="conversational", created_at=start)
        _event(db, conv.id, "completion_confirmed", start + timedelta(minutes=1), {"outcome": 1.0})

    from src.api.main import get_impact_metrics

    impact = await get_impact_metrics(days=30, db=db)
    assert impact["repeatUsers"]["basis"] == "zoho-contact"
    assert impact["repeatUsers"]["zohoLinked"] == 2
    # Two phones merge into one active human; that one human is a repeat user.
    assert impact["repeatUsers"]["activeUsers"] == 1
    assert impact["repeatUsers"]["repeatUsers"] == 1
    assert impact["repeatUsers"]["repeatRate"] == 100.0


@pytest.mark.asyncio
async def test_repeat_users_fallback_to_phone_when_unlinked():
    db = PostgresDB()
    now = datetime.utcnow()
    start = now - timedelta(hours=3)

    user = db.get_or_create_user("256700000711")
    for _ in range(2):
        conv = db.create_conversation(user_id=str(user.id), mode="conversational", created_at=start)
        _event(db, conv.id, "completion_confirmed", start + timedelta(minutes=1), {"outcome": 1.0})

    from src.api.main import get_impact_metrics

    impact = await get_impact_metrics(days=30, db=db)
    assert impact["repeatUsers"]["basis"] == "phone-based"
    assert impact["repeatUsers"]["activeUsers"] == 1
    assert impact["repeatUsers"]["repeatUsers"] == 1