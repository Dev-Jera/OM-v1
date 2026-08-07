import pytest

from src.integrations.clients.mocks.premium_mocks.travel_insurance import build_travel_insurance_premium_mock


@pytest.fixture
def valid_payload():
    return {
        "data": {
            "firstName": " Jane ",
            "middleName": " M ",
            "surname": " Doe ",
            "mobile": "07 7123-4567",
            "email": " Jane.Doe@Example.COM ",
            "coverLevel": "worldwide_essential",
            "whoAreYouCovering": "myself",
            "departureCountry": "Kenya",
            "destinationCountries": "Kenya",
            "travelStartDate": "2099-04-10",
            "travelEndDate": "2099-04-15",
            "travellerDob": "1990-05-10",
        }
    }


def test_travel_mock_enforces_and_normalizes(valid_payload):
    result = build_travel_insurance_premium_mock(valid_payload)

    assert result["total_usd"] > 0
    assert result["total_ugx"] > 0

    breakdown = result["breakdown"]
    assert breakdown["departureCountry"] == "Uganda"
    assert breakdown["durationOfTravel"] == 6
    assert breakdown["numberOfTravellers"] == 1
    assert breakdown["normalized"]["email"] == "jane.doe@example.com"
    assert breakdown["normalized"]["mobile"] == "+256771234567"


def test_travel_mock_requires_valid_phone(valid_payload):
    payload = dict(valid_payload)
    payload["data"] = dict(valid_payload["data"])
    payload["data"]["mobile"] = "12345"

    with pytest.raises(ValueError) as exc:
        build_travel_insurance_premium_mock(payload)

    assert "mobile" in str(exc.value)


def test_travel_mock_requires_date_rules(valid_payload):
    payload = dict(valid_payload)
    payload["data"] = dict(valid_payload["data"])
    payload["data"]["travelStartDate"] = "2000-01-01"

    with pytest.raises(ValueError) as exc:
        build_travel_insurance_premium_mock(payload)

    assert "travelStartDate" in str(exc.value)
