import pytest

from src.integrations.zoho.collectors.crm_products import ZohoCRMError
from src.integrations.zoho.crm_writer import ZohoCRMWriter


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, json=None, headers=None, timeout=None, **kwargs):
        self.requests.append({"method": method, "url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


class FakeTokenManager:
    def __init__(self):
        self.calls = []
        self.api_base_url = "https://www.zohoapis.com"

    def get_access_token(self, force=False):
        self.calls.append(force)
        return "TOKEN"


def test_create_posts_to_module_url():
    session = FakeSession([FakeResponse(200, {"status": "success"})])
    writer = ZohoCRMWriter(FakeTokenManager(), "Mia_Escalations", session=session)

    resp = writer.create([{"Reason": "test"}])

    assert resp == {"status": "success"}
    req = session.requests[0]
    assert req["method"] == "POST"
    assert req["url"] == "https://www.zohoapis.com/crm/v2/Mia_Escalations"
    assert req["json"] == {"data": [{"Reason": "test"}]}
    assert req["headers"]["Authorization"] == "Zoho-oauthtoken TOKEN"


def test_upsert_puts_with_duplicate_check_fields():
    session = FakeSession([FakeResponse(200, {"status": "success"})])
    writer = ZohoCRMWriter(FakeTokenManager(), "Mia_Bot_Metrics", session=session)

    writer.upsert([{"Metric_Date": "2026-08-18"}], ["Metric_Date"])

    req = session.requests[0]
    assert req["method"] == "POST"
    assert req["url"] == "https://www.zohoapis.com/crm/v2/Mia_Bot_Metrics/upsert"
    assert req["json"] == {
        "data": [{"Metric_Date": "2026-08-18"}],
        "duplicate_check_fields": ["Metric_Date"],
    }


def test_401_retries_with_forced_refresh():
    session = FakeSession([FakeResponse(401, {}, "unauthorized"), FakeResponse(200, {"status": "success"})])
    token_manager = FakeTokenManager()
    writer = ZohoCRMWriter(token_manager, "Mia_Bot_Metrics", session=session)

    writer.create([{"Metric_Date": "2026-08-18"}])

    assert len(session.requests) == 2
    assert token_manager.calls == [False, True]


def test_http_error_raises():
    session = FakeSession([FakeResponse(500, {}, "boom")])
    writer = ZohoCRMWriter(FakeTokenManager(), "Mia_Bot_Metrics", session=session)

    with pytest.raises(ZohoCRMError):
        writer.create([{"Metric_Date": "2026-08-18"}])
