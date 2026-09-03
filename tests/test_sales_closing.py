import pytest

from src.chatbot.modes.conversational import (
    SALES_STAGES,
    _advance_sales_stage,
    ConversationalMode,
)
from src.chatbot.sales_closing import (
    PORTAL_LINKS,
    build_buy_block,
    build_buy_now_cta,
    build_closing_block,
    contact_block,
    extract_urls,
    format_urls,
    resolve_buy_links,
)
from src.chatbot.state_manager import StateManager
from src.database.postgres import PostgresDB
from src.database.redis import RedisCache


class DummyRAG:
    async def retrieve(self, query, filters=None, top_k=None):
        return [{"payload": {"text": "stub"}}]

    async def generate(self, query, context_docs, conversation_history):
        return {"answer": "ANSWER: stub", "confidence": 0.5, "sources": [{"id": "1"}]}


class NoMatchMatcher:
    def match_products(self, query, top_k=3):
        return []


def _make(db):
    redis = RedisCache()
    sm = StateManager(redis, db)
    user = db.get_or_create_user("256700000112")
    session_id = sm.create_session(str(user.id))
    conv = ConversationalMode(DummyRAG(), NoMatchMatcher(), sm)
    return conv, sm, user, session_id


def test_extract_urls_dedup_and_limits():
    sources = [
        {"payload": {"url": "https://a/page"}},
        {"payload": {"url": "https://a/page"}},
        {"payload": {}},
        {"url": "https://b/page"},
        {"payload": {"url": "https://c/page"}},
    ]
    assert extract_urls(sources, limit=2) == ["https://a/page", "https://b/page"]
    assert extract_urls(sources, limit=3) == ["https://a/page", "https://b/page", "https://c/page"]
    assert extract_urls(None) == []
    assert extract_urls([]) == []


def test_format_urls():
    assert format_urls(None) is None
    assert format_urls([]) is None
    assert format_urls(["https://a"]) == "https://a"
    assert format_urls(["https://a", "https://b"]) == "https://a · https://b"


def test_contact_block_grounded():
    block = contact_block()
    assert "0800 132 700" in block
    assert "careulc@oldmutual.co.ug" in block


def test_buy_now_cta_mentions_reset_and_menu():
    cta = build_buy_now_cta()
    assert "reset the chat" in cta
    assert "main menu" in cta
    assert "Buy Now" in cta


def test_build_closing_block_full():
    block = build_closing_block(
        urls=["https://om.co.ug/travel"],
        product_label="Travel Insurance",
    )
    assert "https://om.co.ug/travel" in block
    assert "Travel Insurance" in block
    assert "What to expect" in block
    assert "email this conversation" in block
    assert "connect you with an agent" in block
    assert "Buy Now" in block
    # Sensitive links only from provided sources - nothing invented.
    assert "placeholder" not in block


def test_build_closing_block_flags_off():
    block = build_closing_block(include_email_note=False, include_agent_offer=False)
    assert "email this conversation" not in block
    assert "connect you with an agent" not in block
    assert "Buy Now" in block


def test_resolve_buy_links_by_category():
    motor = resolve_buy_links("Motor Insurance", "motor-insurance", "https://www.oldmutual.co.ug/other/motor")
    assert motor[0] == "https://www.oldmutual.co.ug/app/public/motor-insurance"

    invest = resolve_buy_links("Unit Trust", "unit-trust-general", "https://www.oldmutual.co.ug/investment/unit-trust")
    assert invest[0] == "https://client-portal.oldmutual.co.ug/"

    sec = resolve_buy_links("Securities Trading", "securities-trading", "https://www.oldmutual.co.ug/investment/securities-trading")
    assert sec[0] == "http://scd.use.or.ug/"
    assert "https://www.oldmutual.co.ug/investment/securities-trading" in sec

    fallback = resolve_buy_links("Serenicare", "serenicare", "https://www.oldmutual.co.ug/health/serenicare")
    assert fallback == ["https://www.oldmutual.co.ug/health/serenicare"]

    assert resolve_buy_links(None, None, None) == []


def test_build_buy_block_composition():
    block = build_buy_block(
        product_label="Motor Insurance",
        product_id="motor-general",
        product_url="https://www.oldmutual.co.ug/other/motor",
    )
    assert "https://www.oldmutual.co.ug/app/public/motor-insurance" in block
    assert "Motor Insurance" in block
    assert "take it up right here" in block
    assert "What to expect" in block
    assert "email this conversation" in block
    assert "connect you with an agent" in block
    assert "Buy Now" in block
    assert build_buy_now_cta() in block
    # No invented placeholder links.
    assert "placeholder" not in block


def test_build_buy_block_flags_off():
    block = build_buy_block(include_email_note=False, include_agent_offer=False)
    assert "email this conversation" not in block
    assert "connect you with an agent" not in block
    assert "Buy Now" in block


def test_portal_links_are_grounded():
    assert len(PORTAL_LINKS) >= 3
    assert any("client-portal.oldmutual.co.ug" in link for _, link in PORTAL_LINKS)
    assert any("scd.use.or.ug" in link for _, link in PORTAL_LINKS)
    assert any("motor-insurance" in link for _, link in PORTAL_LINKS)


def test_advance_sales_stage_forward_only():
    ctx = {}
    # No products -> stays awareness.
    assert _advance_sales_stage(ctx, "learn", "what is insurance", []) == "awareness"
    # Learning with products -> interest.
    assert _advance_sales_stage(ctx, "learn", "what is insurance", [("x", "m", {"name": "A"})]) == "interest"
    # Price talk -> consideration.
    assert _advance_sales_stage(ctx, "general", "how much is the premium", []) == "consideration"
    # Buy -> decision.
    assert _advance_sales_stage(ctx, "buy", "i want to buy", []) == "decision"
    assert ctx["sales_stage"] == "decision"
    # Never regresses.
    assert _advance_sales_stage(ctx, "learn", "tell me more", [("x", "m", {"name": "A"})]) == "decision"


@pytest.mark.asyncio
async def test_resolved_goodbye_uses_saved_urls_and_context():
    db = PostgresDB()
    conv, sm, user, session_id = _make(db)

    # Inject a product topic + last urls as if a product conversation happened.
    session = sm.get_session(session_id)
    ctx = dict(session["context"] or {})
    ctx["product_topic"] = {"name": "Travel Insurance", "url": "https://om.co.ug/travel"}
    ctx["last_urls"] = ["https://om.co.ug/travel"]
    sm.update_session(session_id, {"context": ctx})

    await conv.process("bye", session_id, str(user.id))
    out = await conv.process("yes", session_id, str(user.id))

    assert out["outcome"] == "resolved"
    r = out["response"]
    assert "https://om.co.ug/travel" in r
    assert "Travel Insurance" in r
    assert "Buy Now" in r
    assert sm.get_session(session_id) is None


@pytest.mark.asyncio
async def test_buy_intent_returns_buy_block_once():
    db = PostgresDB()
    conv, sm, user, session_id = _make(db)

    # Stand in for a product conversation that already happened.
    session = sm.get_session(session_id)
    ctx = dict(session["context"] or {})
    ctx["product_topic"] = {"name": "Travel Insurance", "doc_id": "travel-sure-plus", "url": "https://om.co.ug/travel"}
    ctx["last_urls"] = ["https://om.co.ug/travel"]
    sm.update_session(session_id, {"context": ctx})

    first = await conv.process("i want to buy travel insurance", session_id, str(user.id))
    r = first["response"]
    assert "take it up right here" in r
    assert "What to expect" in r
    assert "email this conversation" in r
    assert "Buy Now" in r

    second = await conv.process("yes buy it", session_id, str(user.id))
    assert "take it up right here" not in second["response"]