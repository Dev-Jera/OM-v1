import os

from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def test_general_information_fetch():
    os.environ["API_KEYS"] = "test-key"
    from src.api.main import app
    client = TestClient(app)
    response = client.get(
        "/api/v1/general-information",
        params={"session_id": "any", "product": "motor_private"},
        headers={"X-API-KEY": "test-key"},
    )
    print("General Information Response:", response.json())
    assert response.status_code == 200
    info = response.json()
    assert info["definition"] == "Motor Private insurance covers privately owned vehicles against risks such as theft, accident, and fire."
    assert "Comprehensive coverage for accidents" in info["benefits"]
    assert info["eligibility"] == "Available to individuals with privately registered vehicles."
    assert isinstance(info["sections"], list)
    assert info["sections"][0]["heading"] == "Definition"
    assert info["sections"][1]["heading"] == "Benefits"
    assert info["sections"][1]["content_type"] == "list"
    assert "Motor Private" in info["readable_text"]
    assert "Definition:" in info["readable_text"]
    assert "Benefits:" in info["readable_text"]
