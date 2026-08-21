from fastapi.testclient import TestClient

from src.api.main import app, postgres_db
from src.chatbot.dependencies import api_key_protection


client = TestClient(app)


def _auth_bypass():
    return None


def test_session_response_includes_known_visitor_name():
    app.dependency_overrides[api_key_protection] = _auth_bypass
    try:
        r1 = client.post("/api/v1/session", json={})
        assert r1.status_code == 200
        body1 = r1.json()
        assert body1["name"] is None

        user = postgres_db.get_or_create_user(phone_number=body1["user_id"])
        postgres_db.set_user_identity(user.id, name="John", email="john.doe@example.com")

        r2 = client.post("/api/v1/session", json={})
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2["user_id"] == body1["user_id"]
        assert body2["name"] == "John"
    finally:
        app.dependency_overrides.pop(api_key_protection, None)
