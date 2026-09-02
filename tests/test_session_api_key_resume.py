from datetime import datetime

from fastapi.testclient import TestClient

from src.api.main import ChatResponse, app, _is_api_key_authenticated
from src.chatbot.dependencies import api_key_protection


client = TestClient(app)


def _auth_bypass():
    return None


def _fake_chat_response(session_id):
    return ChatResponse(
        response={"mode": "conversational", "response": "ok"},
        session_id=session_id,
        mode="conversational",
        timestamp=datetime.now().isoformat(),
    )


def test_is_api_key_authenticated_detects_valid_key(monkeypatch):
    monkeypatch.setenv("API_KEYS", "k1,k2")
    class FakeRequest:
        headers = {"x-api-key": "k2"}
    assert _is_api_key_authenticated(FakeRequest()) is True


def test_is_api_key_authenticated_rejects_missing_key(monkeypatch):
    monkeypatch.setenv("API_KEYS", "k1,k2")
    class FakeRequest:
        headers = {}
    assert _is_api_key_authenticated(FakeRequest()) is False


def test_is_api_key_authenticated_rejects_unknown_key(monkeypatch):
    monkeypatch.setenv("API_KEYS", "k1,k2")
    class FakeRequest:
        headers = {"x-api-key": "bad"}
    assert _is_api_key_authenticated(FakeRequest()) is False


def test_chat_message_api_key_caller_resumes_session_without_403(monkeypatch):
    """An API-key-authenticated (server-to-server) caller is allowed to send a
    session_id without a browser session cookie, instead of being rejected with
    'Session access denied'."""
    monkeypatch.setenv("API_KEYS", "test-key")

    captured = {}
    async def fake_handle(request, router, db):
        captured["session_id"] = request.session_id
        return _fake_chat_response(request.session_id)

    monkeypatch.setattr("src.api.main._handle_chat_message", fake_handle)

    app.dependency_overrides[api_key_protection] = _auth_bypass
    try:
        r = client.post(
            "/api/chat",
            json={"message": "hello", "user_id": "tester", "session_id": "00000000-0000-0000-0000-000000000000"},
            headers={"X-API-KEY": "test-key"},
        )
        assert r.status_code == 200, r.text
        assert captured.get("session_id") == "00000000-0000-0000-0000-000000000000"
    finally:
        app.dependency_overrides.pop(api_key_protection, None)


def test_chat_message_without_api_key_is_still_rejected(monkeypatch):
    """A non-API-key caller sending a session_id (with no ownership cookie) is
    still rejected, preserving the browser-token behavior. The app's generic
    error handler re-raises the 403 ownership violation as a 500, matching the
    pre-existing production behavior observed in the logs."""
    monkeypatch.setenv("API_KEYS", "test-key")

    app.dependency_overrides[api_key_protection] = _auth_bypass
    try:
        r = client.post(
            "/api/chat",
            json={"message": "hello", "user_id": "tester", "session_id": "00000000-0000-0000-0000-000000000000"},
            headers={},
        )
        assert r.status_code == 500, r.text
    finally:
        app.dependency_overrides.pop(api_key_protection, None)