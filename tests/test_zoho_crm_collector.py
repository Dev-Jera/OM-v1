import pytest

from src.integrations.zoho.collectors.crm_products import ZohoCRMError, ZohoCRMProductsCollector


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
        self.gets = []

    def get(self, url, params=None, headers=None, timeout=None, **kwargs):
        self.gets.append({"url": url, "params": params, "headers": headers})
        return self.responses.pop(0)


class FakeTokenManager:
    def __init__(self):
        self.calls = []
        self.api_base_url = "https://www.zohoapis.com"

    def get_access_token(self, force=False):
        self.calls.append(force)
        return "TOKEN"


def _records(n, start=1):
    return [{"id": str(i), "Product_Name": f"Product {i}"} for i in range(start, start + n)]


def test_pagination_collects_all_pages():
    session = FakeSession(
        [
            FakeResponse(200, {"data": _records(2, 1), "info": {"more_records": True, "page": 1}}),
            FakeResponse(200, {"data": _records(2, 3), "info": {"more_records": False, "page": 2}}),
        ]
    )
    collector = ZohoCRMProductsCollector(FakeTokenManager(), session=session)

    records = collector.fetch_records()

    assert len(records) == 4
    assert len(session.gets) == 2
    assert session.gets[0]["params"]["page"] == 1
    assert session.gets[1]["params"]["page"] == 2
    assert session.gets[0]["headers"]["Authorization"] == "Zoho-oauthtoken TOKEN"


def test_limit_stops_early():
    session = FakeSession([FakeResponse(200, {"data": _records(10), "info": {"more_records": True, "page": 1}})])
    collector = ZohoCRMProductsCollector(FakeTokenManager(), session=session)

    records = collector.fetch_records(limit=3)

    assert len(records) == 3
    assert len(session.gets) == 1


def test_fields_param_is_comma_joined():
    session = FakeSession([FakeResponse(200, {"data": [], "info": {"more_records": False}})])
    collector = ZohoCRMProductsCollector(
        FakeTokenManager(), session=session, fields=["id", "Product_Name", "Description"]
    )

    collector.fetch_records()

    assert session.gets[0]["params"]["fields"] == "id,Product_Name,Description"


def test_401_retries_with_forced_refresh():
    session = FakeSession(
        [
            FakeResponse(401, {}, "unauthorized"),
            FakeResponse(200, {"data": _records(1), "info": {"more_records": False}}),
        ]
    )
    token_manager = FakeTokenManager()
    collector = ZohoCRMProductsCollector(token_manager, session=session)

    records = collector.fetch_records()

    assert len(records) == 1
    assert len(session.gets) == 2
    assert token_manager.calls == [False, True], "first call cached, retry forces a refresh"


def test_http_error_raises_zoho_crm_error():
    session = FakeSession([FakeResponse(500, {}, "boom")])
    collector = ZohoCRMProductsCollector(FakeTokenManager(), session=session)

    with pytest.raises(ZohoCRMError):
        collector.fetch_records()
