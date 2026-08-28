import pytest
from httpx import AsyncClient, ASGITransport

from src.api.complaints import router
from src.chatbot.dependencies import api_key_protection
from src.database.postgres import PostgresDB


async def _auth_bypass():
    return True


@pytest.fixture(autouse=True)
def _set_db_and_bypass_auth():
    """Wire the complaints module to an in-memory PostgresDB and bypass API key."""
    from src.api.main import app

    import src.api.complaints as mod

    mod.db = PostgresDB()
    app.dependency_overrides[api_key_protection] = _auth_bypass
    yield
    mod.db = None
    app.dependency_overrides.pop(api_key_protection, None)


def _make_client():
    from src.api.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_file_complaint_success():
    async with _make_client() as client:
        resp = await client.post(
            "/api/v1/complaints",
            json={
                "name": "Jane Doe",
                "email": "jane@example.com",
                "category": "billing",
                "complaint": "I was overcharged on my premium",
            },
        )
    body = resp.json()
    assert body["success"] is True
    assert "complaint_id" in body
    assert body["message"]


@pytest.mark.asyncio
async def test_file_complaint_missing_name():
    async with _make_client() as client:
        resp = await client.post(
            "/api/v1/complaints",
            json={
                "name": "",
                "email": "jane@example.com",
                "category": "billing",
                "complaint": "overcharged",
            },
        )
    body = resp.json()
    assert body["success"] is False
    assert "name" in body["error"].lower()


@pytest.mark.asyncio
async def test_file_complaint_missing_email():
    async with _make_client() as client:
        resp = await client.post(
            "/api/v1/complaints",
            json={
                "name": "Jane",
                "email": "",
                "category": "service",
                "complaint": "bad service",
            },
        )
    body = resp.json()
    assert body["success"] is False
    assert "email" in body["error"].lower()


@pytest.mark.asyncio
async def test_file_complaint_missing_complaint_text():
    async with _make_client() as client:
        resp = await client.post(
            "/api/v1/complaints",
            json={
                "name": "Jane",
                "email": "jane@example.com",
                "category": "product",
                "complaint": "",
            },
        )
    body = resp.json()
    assert body["success"] is False
    assert "complaint" in body["error"].lower()


@pytest.mark.asyncio
async def test_file_complaint_invalid_category_defaults_to_other():
    async with _make_client() as client:
        resp = await client.post(
            "/api/v1/complaints",
            json={
                "name": "Jane",
                "email": "jane@example.com",
                "category": "nonexistent",
                "complaint": "something went wrong",
            },
        )
    body = resp.json()
    assert body["success"] is True

    complaint_id = body["complaint_id"]
    async with _make_client() as client:
        get_resp = await client.get(f"/api/v1/complaints/{complaint_id}")
    assert get_resp.json()["complaint"]["category"] == "other"


@pytest.mark.asyncio
async def test_get_complaint_found():
    async with _make_client() as client:
        post_resp = await client.post(
            "/api/v1/complaints",
            json={
                "name": "Bob",
                "email": "bob@example.com",
                "category": "claims",
                "complaint": "My claim was denied unfairly",
            },
        )
        complaint_id = post_resp.json()["complaint_id"]

        get_resp = await client.get(f"/api/v1/complaints/{complaint_id}")
    body = get_resp.json()
    assert body["success"] is True
    assert body["complaint"]["name"] == "Bob"
    assert body["complaint"]["email"] == "bob@example.com"
    assert body["complaint"]["category"] == "claims"
    assert body["complaint"]["status"] == "submitted"


@pytest.mark.asyncio
async def test_get_complaint_not_found():
    async with _make_client() as client:
        resp = await client.get("/api/v1/complaints/nonexistent-id")
    body = resp.json()
    assert body["success"] is False
    assert "not found" in body["error"].lower()


@pytest.mark.asyncio
async def test_list_complaints_returns_all():
    async with _make_client() as client:
        for i in range(3):
            await client.post(
                "/api/v1/complaints",
                json={
                    "name": f"User {i}",
                    "email": f"user{i}@example.com",
                    "category": "other",
                    "complaint": f"Complaint #{i}",
                },
            )

        resp = await client.get("/api/v1/complaints")
    body = resp.json()
    assert body["success"] is True
    assert len(body["complaints"]) >= 3


@pytest.mark.asyncio
async def test_list_complaints_filter_by_user_id():
    async with _make_client() as client:
        await client.post(
            "/api/v1/complaints",
            json={
                "name": "Alice",
                "email": "alice@example.com",
                "category": "billing",
                "complaint": "wrong bill",
            },
        )

        resp = await client.get("/api/v1/complaints?user_id=nonexistent")
    body = resp.json()
    assert body["success"] is True
    assert all(c["user_id"] != "nonexistent" for c in body["complaints"])


@pytest.mark.asyncio
async def test_complaint_anonymous_user_id():
    async with _make_client() as client:
        resp = await client.post(
            "/api/v1/complaints",
            json={
                "name": "Anon",
                "email": "anon@example.com",
                "category": "other",
                "complaint": "test",
            },
        )
        complaint_id = resp.json()["complaint_id"]
        get_resp = await client.get(f"/api/v1/complaints/{complaint_id}")
    body = get_resp.json()
    assert body["complaint"]["user_id"] == "anonymous"
