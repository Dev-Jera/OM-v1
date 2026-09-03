import pytest

from src.chatbot.modes.conversational import ConversationalMode
from src.chatbot.product_classifier import ProductClassifier, ProductPick, NO_PRODUCT
from src.chatbot.state_manager import StateManager
from src.database.postgres import PostgresDB
from src.database.redis import RedisCache


class FakeClient:
    """Minimal stand-in for a Gemini client returning a fixed text."""

    def __init__(self, text=None, raise_on=False):
        self._text = text
        self._raise_on = raise_on

        class _Models:
            def __init__(self, owner):
                self._owner = owner

            def generate_content(self, model=None, contents=None, config=None):
                if self._owner._raise_on:
                    raise RuntimeError("boom")

                class _Resp:
                    text = self._owner._text

                return _Resp()

        self.models = _Models(self)


class FakeClassifier:
    """Double for ProductClassifier: fixed ProductPick + call counter."""

    def __init__(self, pick: ProductPick):
        self._pick = pick
        self.calls = 0

    def available(self):
        return True

    async def recognize(self, message, product_names):
        self.calls += 1
        return self._pick


class DummyRAG:
    async def retrieve(self, query, filters=None, top_k=None):
        return [{"payload": {"text": "stub"}}]

    async def generate(self, query, context_docs, conversation_history):
        return {"answer": f"ANSWER: {query}", "confidence": 0.5, "sources": []}


def _prod(pid, name, cat):
    return {"product_id": pid, "doc_id": pid, "name": name, "category_name": cat, "sub_category_name": cat, "url": "https://oldmutual.ug"}


class WrongPickMatcher:
    """Returns the WRONG product (the pre-fix bug) at low confidence, plus a catalog."""

    product_index = {}
    for _p in [_prod("website:product:field/crop-insurance", "Crop Insurance", "Agriculture"),
               _prod("website:product:motor/motor-insurance", "Motor Insurance", "Motor")]:
        product_index[_p["product_id"]] = _p

    def match_products(self, query, top_k=3):
        # Matcher (no synonyms) wrongly picks Crop Insurance for "comprehensive insurance".
        return [(0.6, 0, self.product_index["website:product:field/crop-insurance"])]


class ConfidentAccidentMatcher:
    """Returns an unambiguous exact-name match at high score."""

    product_index = {
        "website:product:personal/personal-accident": _prod(
            "website:product:personal/personal-accident", "Personal Accident", "Personal"
        )
    }

    def match_products(self, query, top_k=3):
        return [(3.5, 0, self.product_index["website:product:personal/personal-accident"])]


@pytest.fixture
def state():
    db = PostgresDB()
    return (StateManager(RedisCache(), db), db)


@pytest.mark.asyncio
async def test_integration_llm_overrides_wrong_matcher_pick(state):
    sm, db = state
    user = db.get_or_create_user(phone_number="256700800001")
    session_id = sm.create_session(str(user.id))
    classifier = FakeClassifier(ProductPick("Motor Insurance", True))
    conv = ConversationalMode(DummyRAG(), WrongPickMatcher(), sm, product_classifier=classifier)
    await conv.process("how much is a comprehensive insurance", session_id, str(user.id))
    ctx = (sm.get_session(session_id) or {}).get("context") or {}
    assert (ctx.get("product_topic") or {}).get("name") == "Motor Insurance"


@pytest.mark.asyncio
async def test_integration_llm_none_falls_back_to_matcher(state):
    sm, db = state
    user = db.get_or_create_user(phone_number="256700800002")
    session_id = sm.create_session(str(user.id))
    classifier = FakeClassifier(NO_PRODUCT)
    conv = ConversationalMode(DummyRAG(), WrongPickMatcher(), sm, product_classifier=classifier)
    await conv.process("tell me about comprehensive insurance", session_id, str(user.id))
    ctx = (sm.get_session(session_id) or {}).get("context") or {}
    # No valid LLM pick -> matcher result captured (Crop Insurance here).
    assert (ctx.get("product_topic") or {}).get("name") == "Crop Insurance"


@pytest.mark.asyncio
async def test_integration_skip_when_matcher_confident(state):
    sm, db = state
    user = db.get_or_create_user(phone_number="256700800003")
    session_id = sm.create_session(str(user.id))
    classifier = FakeClassifier(ProductPick("Personal Accident", True))
    conv = ConversationalMode(DummyRAG(), ConfidentAccidentMatcher(), sm, product_classifier=classifier)
    await conv.process("personal accident", session_id, str(user.id))
    ctx = (sm.get_session(session_id) or {}).get("context") or {}
    assert (ctx.get("product_topic") or {}).get("name") == "Personal Accident"
    # Exact-name match is confident -> the LLM classifier should be skipped.
    assert classifier.calls == 0


@pytest.mark.asyncio
async def test_integration_unmatched_sets_interest_and_not_product_name(state):
    sm, db = state
    user = db.get_or_create_user(phone_number="256700800004")
    session_id = sm.create_session(str(user.id))
    # LLM says we don't sell it -> capture unmatched, suppress noisy matcher pick.
    classifier = FakeClassifier(ProductPick("health insurance", False))
    conv = ConversationalMode(DummyRAG(), WrongPickMatcher(), sm, product_classifier=classifier)
    await conv.process("i need health insurance", session_id, str(user.id))
    ctx = (sm.get_session(session_id) or {}).get("context") or {}
    assert (ctx.get("unmatched_interest")) == "health insurance"
    # Product_Name must NOT be the wrong matcher pick when LM says non-catalog.
    assert not (ctx.get("product_topic") or {}).get("name")


PRODUCTS = ["Motor Insurance", "Motor Commercial", "Crop Insurance", "Personal Accident"]


@pytest.mark.asyncio
async def test_recognize_picks_matching_product():
    classifier = ProductClassifier(client=FakeClient("Motor Insurance"))
    result = await classifier.recognize("how much is a car insurance", PRODUCTS)
    assert result.name == "Motor Insurance"
    assert result.in_catalog is True


@pytest.mark.asyncio
async def test_recognize_captures_unmatched_product():
    # Model returns a product NOT in the catalog -> kept as unmatched interest.
    classifier = ProductClassifier(client=FakeClient("Health Insurance"))
    result = await classifier.recognize("i need health insurance", PRODUCTS)
    assert result.name == "Health Insurance"
    assert result.in_catalog is False


@pytest.mark.asyncio
async def test_recognize_returns_none_on_no_match():
    classifier = ProductClassifier(client=FakeClient("none"))
    result = await classifier.recognize("which products do you offer", PRODUCTS)
    assert result is NO_PRODUCT or (result.name is None and result.in_catalog is False)


@pytest.mark.asyncio
async def test_recognize_returns_none_on_error():
    classifier = ProductClassifier(client=FakeClient(raise_on=True))
    result = await classifier.recognize("car insurance", PRODUCTS)
    assert result is NO_PRODUCT or (result.name is None and result.in_catalog is False)


@pytest.mark.asyncio
async def test_recognize_empty_message_returns_none():
    classifier = ProductClassifier(client=FakeClient("Motor Insurance"))
    assert await classifier.recognize("", PRODUCTS) is NO_PRODUCT
    assert await classifier.recognize("   ", PRODUCTS) is NO_PRODUCT


@pytest.mark.asyncio
async def test_recognize_no_catalog_returns_none():
    classifier = ProductClassifier(client=FakeClient("Motor Insurance"))
    assert await classifier.recognize("motor insurance", []) is NO_PRODUCT


@pytest.mark.asyncio
async def test_product_pick_bool():
    assert bool(ProductPick("x", True)) is True
    assert bool(ProductPick(None, False)) is False
    assert bool(NO_PRODUCT) is False
