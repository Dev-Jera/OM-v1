import pytest

from src.chatbot.flows.router import ChatRouter
from src.chatbot.modes.conversational import ConversationalMode
from src.chatbot.modes.guided import GuidedMode
from src.chatbot.state_manager import StateManager
from src.database.postgres import PostgresDB
from src.database.redis import RedisCache


class DummyRAG:
    async def retrieve(self, query, filters=None, top_k=None):
        return [{"payload": {"text": "stub"}}]

    async def generate(self, query, context_docs, conversation_history):
        return {"answer": "ANSWER: stub", "confidence": 0.5, "sources": [{"id": "1"}]}


class DummyMatcher:
    def match_products(self, query, top_k=3):
        return []


class DummyGuided:
    async def process(self, *args, **kwargs):
        raise AssertionError("guided.process should not be called")

    async def start_flow(self, *args, **kwargs):
        raise AssertionError("guided.start_flow should not be called")


def _paths(db):
    from datetime import datetime

    return [
        e
        for e in db.list_conversation_events(start=datetime.min, end=datetime.max)
        if e.event_type == "conversation_path"
    ]


@pytest.mark.asyncio
async def test_freeform_chat_records_freeform_path():
    db = PostgresDB()
    redis = RedisCache()
    sm = StateManager(redis, db)
    user = db.get_or_create_user("256700000511")
    session_id = sm.create_session(str(user.id))

    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm)
    await conv.process("What is comprehensive motor insurance?", session_id, str(user.id))

    paths = _paths(db)
    assert len(paths) == 1
    assert paths[0].payload["path"] == "freeform"
    assert paths[0].payload["source"] == "chat"


@pytest.mark.asyncio
async def test_connect_agent_button_records_direct_agent_path():
    db = PostgresDB()
    redis = RedisCache()
    sm = StateManager(redis, db)
    user = db.get_or_create_user("256700000522")
    session_id = sm.create_session(str(user.id))

    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm)
    router = ChatRouter(conv, DummyGuided(), sm, DummyMatcher())

    await router.route("", session_id, str(user.id), form_data={"action": "connect_agent"})

    paths = _paths(db)
    assert len(paths) == 1
    assert paths[0].payload["path"] == "direct_agent"
    assert paths[0].payload["source"] == "button"


@pytest.mark.asyncio
async def test_escalate_endpoint_records_direct_agent_path():
    import src.api.escalation as escalation_api

    db = PostgresDB()
    redis = RedisCache()
    sm = StateManager(redis, db)
    user = db.get_or_create_user("256700000533")
    session_id = sm.create_session(str(user.id))

    escalation_api.state_manager = sm
    response = await escalation_api.escalate(
        escalation_api.EscalateRequest(session_id=session_id, reason="user_requested_agent")
    )
    assert response["escalated"] is True

    paths = _paths(db)
    assert len(paths) == 1
    assert paths[0].payload["path"] == "direct_agent"
    assert paths[0].payload["source"] == "escalate_endpoint"


@pytest.mark.asyncio
async def test_guided_start_records_guided_flow_path():
    db = PostgresDB()
    redis = RedisCache()
    sm = StateManager(redis, db)
    user = db.get_or_create_user("256700000544")
    session_id = sm.create_session(str(user.id))

    guided = GuidedMode(sm, None, db)
    out = await guided.start_flow("discovery", session_id, str(user.id))
    assert out["mode"] == "guided"

    paths = _paths(db)
    assert len(paths) == 1
    assert paths[0].payload["path"] == "guided_flow"
    assert paths[0].payload["source"] == "start_flow"


@pytest.mark.asyncio
async def test_first_path_wins():
    db = PostgresDB()
    redis = RedisCache()
    sm = StateManager(redis, db)
    user = db.get_or_create_user("256700000555")
    session_id = sm.create_session(str(user.id))

    conv = ConversationalMode(DummyRAG(), DummyMatcher(), sm)
    router = ChatRouter(conv, DummyGuided(), sm, DummyMatcher())

    # User first chats freely, then asks for an agent.
    await conv.process("Hello, I need help.", session_id, str(user.id))
    await router.route("", session_id, str(user.id), form_data={"action": "connect_agent"})

    paths = _paths(db)
    assert len(paths) == 1
    assert paths[0].payload["path"] == "freeform"