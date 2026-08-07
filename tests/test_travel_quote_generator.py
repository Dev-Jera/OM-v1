from src.integrations.clients.real_http.travel_quote_generator import generate_travel_quote


class _DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_generate_travel_quote_success(monkeypatch):
    def _fake_post(url, json, headers, timeout):
        assert "getTravelQuoteDocWithBankDetails" in url
        assert json["products"][0]["quote_id"] == "Q-123"
        return _DummyResponse(
            {
                "success": True,
                "benefitsSummary": "API benefits summary",
                "previewUrl": "https://example.com/preview.pdf",
            }
        )

    monkeypatch.setattr("requests.post", _fake_post)

    result = generate_travel_quote(
        {
            "quoteid": "Q-123",
            "priceInclTax": 55.0,
            "clientName": "Jane Doe",
            "planName": "Worldwide Essential",
            "durationDays": 6,
            "formattedStartDate": "2026-04-10",
            "formattedEndDate": "2026-04-15",
            "destinationArea": "Kenya",
            "adults": 1,
            "children": 0,
            "seniors": 0,
        }
    )

    assert result["benefits"] == "API benefits summary"
    assert result["benefitsUrl"] == "https://example.com/preview.pdf"


def test_generate_travel_quote_requires_quote_id_and_price():
    try:
        generate_travel_quote(
            {
                "quoteid": "",
                "priceInclTax": 0,
                "planName": "Worldwide Elite",
            }
        )
        assert False, "Expected ValueError for missing required real-api inputs"
    except ValueError as exc:
        assert "quoteid" in str(exc) or "priceInclTax" in str(exc)
