from src.utils.pii_redaction import (
    PHONE_MASK,
    EMAIL_MASK,
    ID_MASK,
    DIGITS_MASK,
    clean_history,
    is_structured_payload,
    redact_history,
    redact_text,
)


def test_redacts_ugandan_mobile_phone():
    masked, counts = redact_text("Call me on 0771234567 today")
    assert PHONE_MASK in masked
    assert "0771234567" not in masked
    assert counts[PHONE_MASK] == 1


def test_redacts_international_phone():
    masked, counts = redact_text("Reach me at +256701234567 anytime")
    assert PHONE_MASK in masked
    assert "+256701234567" not in masked
    assert counts[PHONE_MASK] == 1


def test_redacts_spaced_phone():
    masked, _ = redact_text("my number is 0771 234 567")
    assert PHONE_MASK in masked
    assert "0771 234 567" not in masked


def test_redacts_email():
    masked, counts = redact_text("email me at sarah.w@example.co.ug")
    assert EMAIL_MASK in masked
    assert "sarah.w@example.co.ug" not in masked
    assert counts[EMAIL_MASK] == 1


def test_redacts_nin():
    masked, counts = redact_text("My NIN is CF1234567890XY")
    assert ID_MASK in masked
    assert "CF1234567890XY" not in masked
    assert counts[ID_MASK] == 1


def test_redacts_passport():
    masked, counts = redact_text("Passport number B1234567")
    assert ID_MASK in masked
    assert "B1234567" not in masked
    assert counts[ID_MASK] == 1


def test_redacts_long_digit_runs():
    masked, counts = redact_text("account 12345678901234")
    assert DIGITS_MASK in masked
    assert "12345678901234" not in masked
    assert counts[DIGITS_MASK] == 1


def test_does_not_redact_short_regular_words():
    text = "I need travel insurance for my family of four"
    masked, counts = redact_text(text)
    assert masked == text
    assert counts == {}


def test_redacts_multiple_in_one_text():
    text = "phone 0771234567 email a@b.com NIN CF1234567890XY"
    masked, counts = redact_text(text)
    assert PHONE_MASK in masked
    assert EMAIL_MASK in masked
    assert ID_MASK in masked
    assert counts[PHONE_MASK] == 1
    assert counts[EMAIL_MASK] == 1
    assert counts[ID_MASK] == 1


def test_none_input_returns_empty():
    masked, counts = redact_text(None)
    assert masked == ""
    assert counts == {}


def test_redact_history_preserves_roles():
    history = [
        {"role": "user", "content": "my number is 0771234567"},
        {"role": "assistant", "content": "thanks"},
    ]
    out = redact_history(history)
    assert PHONE_MASK in out[0]["content"]
    assert out[0]["role"] == "user"
    assert out[1]["role"] == "assistant"


def test_clean_history_drops_structured_payloads():
    history = [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": "Submitted details:\n- Full name: Sarah\n- Phone: 0771234567"},
        {"role": "user", "content": "{\"full_name\": \"Sarah\"}"},
        {"role": "user", "content": "what next"},
    ]
    out = clean_history(history)
    contents = [m["content"] for m in out]
    assert contents == ["hello", "what next"]


def test_clean_history_drops_form_data_flag():
    history = [
        {"role": "user", "content": "my info", "metadata": {"form_data": {"full_name": "Sarah"}}},
        {"role": "user", "content": "keep me"},
    ]
    out = clean_history(history)
    assert len(out) == 1
    assert out[0]["content"] == "keep me"


def test_is_structured_payload_detects_json_and_prefixes():
    assert is_structured_payload('{"a": 1}')
    assert is_structured_payload("[1, 2, 3]")
    assert is_structured_payload("Submitted details:\n- a: 1")
    assert is_structured_payload("Assistant update:\n- a: 1")
    assert not is_structured_payload("hi there")
