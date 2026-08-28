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
        self.requests.append(
            {"method": method, "url": url, "json": json, "headers": headers, "params": kwargs.get("params")}
        )
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


def test_upsert_search_exists_updates_record():
    existing = {"id": "748410001", "Metric_Date": "2026-08-18", "Name": "2026-08-18"}
    search_hit = {"data": [existing]}
    update_resp = {"data": [{"code": "SUCCESS", "details": {"id": "748410001"}}]}
    session = FakeSession([FakeResponse(200, search_hit), FakeResponse(200, update_resp)])
    writer = ZohoCRMWriter(FakeTokenManager(), "Mia_Bot_Metrics", session=session)

    writer.upsert([{"Name": "2026-08-18", "Metric_Date": "2026-08-18", "Conversations": 3}], ["Metric_Date"])

    search_req, update_req = session.requests
    assert search_req["method"] == "GET"
    assert "criteria=" in search_req["url"] or search_req["params"] is not None
    assert search_req["params"] == {
        "criteria": "(Metric_Date:equals:2026-08-18 and Name:equals:2026-08-18)",
        "per_page": "25",
    }
    assert update_req["method"] == "PUT"
    assert update_req["url"] == "https://www.zohoapis.com/crm/v2/Mia_Bot_Metrics/748410001"
    assert update_req["json"]["Conversations"] == 3


def test_upsert_no_match_creates_record():
    empty_search = {"data": []}
    create_resp = {"data": [{"code": "SUCCESS", "details": {"id": "999"}}]}
    session = FakeSession([FakeResponse(200, empty_search), FakeResponse(200, create_resp)])
    writer = ZohoCRMWriter(FakeTokenManager(), "Mia_Bot_Metrics", session=session)

    writer.upsert([{"Name": "2026-08-18", "Metric_Date": "2026-08-18"}], ["Metric_Date"])

    search_req, create_req = session.requests
    assert search_req["method"] == "GET"
    assert create_req["method"] == "POST"
    assert create_req["url"] == "https://www.zohoapis.com/crm/v2/Mia_Bot_Metrics"
    assert create_req["json"] == {"data": [{"Name": "2026-08-18", "Metric_Date": "2026-08-18"}]}


def test_upsert_matches_null_bucket():
    daily = {"id": "111", "Name": "2026-08-18", "Metric_Date": "2026-08-18", "Metric_Hour": None}
    hourly = {"id": "222", "Name": "2026-08-18-12", "Metric_Date": "2026-08-18", "Metric_Hour": 12}
    search_hit = {"data": [hourly, daily]}
    update_resp = {"data": [{"code": "SUCCESS", "details": {"id": "111"}}]}
    session = FakeSession([FakeResponse(200, search_hit), FakeResponse(200, update_resp)])
    writer = ZohoCRMWriter(FakeTokenManager(), "Mia_Bot_Metrics", session=session)

    writer.upsert([{"Name": "2026-08-18", "Metric_Date": "2026-08-18"}], ["Metric_Date"])

    search_req, update_req = session.requests
    assert search_req["params"] == {
        "criteria": "(Metric_Date:equals:2026-08-18 and Name:equals:2026-08-18)",
        "per_page": "25",
    }
    assert update_req["method"] == "PUT"
    assert update_req["url"] == "https://www.zohoapis.com/crm/v2/Mia_Bot_Metrics/111"


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