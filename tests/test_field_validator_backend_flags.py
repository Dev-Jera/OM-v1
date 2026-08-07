from src.chatbot.field_validator import FieldValidator


def test_requires_backend_includes_frontend_aliases() -> None:
    assert FieldValidator.requires_backend("phone_number") is True
    assert FieldValidator.requires_backend("phoneNumber") is True
    assert FieldValidator.requires_backend("dateOfBirth") is True
    assert FieldValidator.requires_backend("vehicle_value_ugx") is True
    assert FieldValidator.requires_backend("vehicleValueUgx") is True


def test_date_of_birth_alias_is_validated_as_dob_rule() -> None:
    result = FieldValidator.validate("dateOfBirth", "2014-01-01", {})

    assert result["valid"] is False
    assert result["field"] == "dateOfBirth"
    assert "at least 18" in result["error"]
