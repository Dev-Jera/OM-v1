import pytest
from httpx import AsyncClient, ASGITransport

from src.chatbot.dependencies import api_key_protection
from src.database.postgres import PostgresDB


async def _auth_bypass():
    return True


@pytest.fixture(autouse=True)
def _set_db_and_bypass_auth():
    from src.api.main import app
    import src.api.product_logs as mod

    mod.db = PostgresDB()
    app.dependency_overrides[api_key_protection] = _auth_bypass
    yield
    mod.db = None
    app.dependency_overrides.pop(api_key_protection, None)


def _make_client():
    from src.api.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── DB layer tests ──────────────────────────────────────────────

def test_log_product_interest_creates_record():
    db = PostgresDB()
    log = db.log_product_interest("conv-1", "user-1", "Motor Private", "vehicle")
    assert log.id
    assert log.product_name == "Motor Private"
    assert log.product_category == "vehicle"


def test_list_product_logs():
    db = PostgresDB()
    db.log_product_interest("conv-1", "user-1", "Motor Private", "vehicle")
    db.log_product_interest("conv-2", "user-1", "Travel Insurance", "personal")
    logs = db.list_product_logs()
    assert len(logs) == 2


def test_list_product_logs_filter_by_user():
    db = PostgresDB()
    db.log_product_interest("conv-1", "user-1", "Motor Private", "vehicle")
    db.log_product_interest("conv-2", "user-2", "Travel Insurance", "personal")
    logs = db.list_product_logs(user_id="user-1")
    assert len(logs) == 1
    assert logs[0].product_name == "Motor Private"


def test_get_product_log_by_conversation():
    db = PostgresDB()
    db.log_product_interest("conv-99", "user-1", "Serenicare", "personal")
    log = db.get_product_log_by_conversation("conv-99")
    assert log is not None
    assert log.product_name == "Serenicare"
    assert db.get_product_log_by_conversation("nope") is None


# ── API layer tests ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_log_product_api_success():
    async with _make_client() as client:
        resp = await client.post("/api/v1/product-logs", json={
            "conversation_id": "conv-1",
            "user_id": "user-1",
            "product_name": "Motor Private",
            "product_category": "vehicle",
        })
    body = resp.json()
    assert body["success"] is True
    assert "log_id" in body


@pytest.mark.asyncio
async def test_log_product_api_missing_name():
    async with _make_client() as client:
        resp = await client.post("/api/v1/product-logs", json={
            "conversation_id": "conv-1",
            "user_id": "user-1",
            "product_name": "",
            "product_category": "vehicle",
        })
    body = resp.json()
    assert body["success"] is False
    assert "product_name" in body["error"].lower()


@pytest.mark.asyncio
async def test_list_product_logs_api():
    async with _make_client() as client:
        for i in range(3):
            await client.post("/api/v1/product-logs", json={
                "conversation_id": f"conv-{i}",
                "user_id": "user-1",
                "product_name": "Travel Insurance",
                "product_category": "personal",
            })
        resp = await client.get("/api/v1/product-logs")
    body = resp.json()
    assert body["success"] is True
    assert len(body["product_logs"]) >= 3


@pytest.mark.asyncio
async def test_product_popularity_api():
    async with _make_client() as client:
        await client.post("/api/v1/product-logs", json={
            "conversation_id": "c1", "user_id": "u1",
            "product_name": "Motor Private", "product_category": "vehicle",
        })
        await client.post("/api/v1/product-logs", json={
            "conversation_id": "c2", "user_id": "u2",
            "product_name": "Motor Private", "product_category": "vehicle",
        })
        await client.post("/api/v1/product-logs", json={
            "conversation_id": "c3", "user_id": "u3",
            "product_name": "Travel Insurance", "product_category": "personal",
        })
        resp = await client.get("/api/v1/metrics/products")
    body = resp.json()
    assert body["success"] is True
    assert body["total_logs"] >= 3
    names = {p["product_name"] for p in body["by_product"]}
    assert "Motor Private" in names
    assert "Travel Insurance" in names


@pytest.mark.asyncio
async def test_list_product_logs_filter_by_user_api():
    async with _make_client() as client:
        await client.post("/api/v1/product-logs", json={
            "conversation_id": "c1", "user_id": "u1",
            "product_name": "Motor Private", "product_category": "vehicle",
        })
        resp = await client.get("/api/v1/product-logs?user_id=u2")
    body = resp.json()
    assert body["success"] is True
    assert len(body["product_logs"]) == 0
