import pytest

from src.integrations.zoho.oauth import ZohoOAuthError, ZohoTokenManager


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
        self.posts = []

    def post(self, url, data=None, timeout=None, **kwargs):
        self.posts.append({"url": url, "data": data})
        return self.responses.pop(0)


def _manager(session, region="com"):
    return ZohoTokenManager("cid", "csec", "rt", region=region, session=session)


def test_refresh_exchanges_refresh_token_for_access_token():
    session = FakeSession([FakeResponse(200, {"access_token": "AT1", "expires_in": 3600})])
    m = _manager(session)

    token = m.get_access_token()

    assert token == "AT1"
    assert session.posts[0]["url"] == "https://accounts.zoho.com/oauth/v2/token"
    data = session.posts[0]["data"]
    assert data["grant_type"] == "refresh_token"
    assert data["client_id"] == "cid"
    assert data["client_secret"] == "csec"
    assert data["refresh_token"] == "rt"


def test_access_token_is_cached_until_expiry():
    session = FakeSession(
        [FakeResponse(200, {"access_token": "AT1", "expires_in": 3600})]
    )
    m = _manager(session)

    assert m.get_access_token() == "AT1"
    assert m.get_access_token() == "AT1"
    assert len(session.posts) == 1


def test_force_refresh_requests_new_token():
    session = FakeSession(
        [
            FakeResponse(200, {"access_token": "AT1", "expires_in": 3600}),
            FakeResponse(200, {"access_token": "AT2", "expires_in": 3600}),
        ]
    )
    m = _manager(session)

    assert m.get_access_token() == "AT1"
    assert m.get_access_token(force=True) == "AT2"
    assert len(session.posts) == 2


def test_api_base_url_for_region():
    assert _manager(FakeSession([]), region="com").api_base_url == "https://www.zohoapis.com"
    assert _manager(FakeSession([]), region="eu").api_base_url == "https://www.zohoapis.eu"
    assert _manager(FakeSession([]), region="in").api_base_url == "https://www.zohoapis.in"


def test_unsupported_region_raises():
    with pytest.raises(ZohoOAuthError):
        _manager(FakeSession([]), region="zz")


def test_refresh_error_raises_zoho_oauth_error():
    session = FakeSession([FakeResponse(400, {}, "bad request")])
    m = _manager(session)

    with pytest.raises(ZohoOAuthError):
        m.get_access_token()


def test_refresh_missing_access_token_raises():
    session = FakeSession([FakeResponse(200, {"expires_in": 3600})])
    m = _manager(session)

    with pytest.raises(ZohoOAuthError):
        m.get_access_token()
