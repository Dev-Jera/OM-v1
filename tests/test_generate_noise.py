import asyncio

import pytest

from src.chatbot.modes.conversational import _looks_like_noise
from src.rag.generate import MiaGenerator


class _Part:
    def __init__(self, text=None):
        self.text = text


class _Content:
    def __init__(self, parts):
        self.parts = parts


class _Candidate:
    def __init__(self, parts, finish_reason=None):
        self.content = _Content(parts)
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, text="", candidates=None):
        self.text = text
        self.candidates = candidates or []


# --------------------------------------------------------------------------- #
# Noise detection (conversational.py)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "message,expected",
    [
        ("mmmmmmmmmmmmmmmmmmmmmmmmmm", True),   # all-same-character mash
        ("mnmnmnmnmnmnmnmnmnmn", True),         # repetitive 2-char mash
        ("&&&&", True),                          # punctuation only
        ("!!!", True),
        ("!!!!", True),
        ("hi", False),                           # handled by greeting intent anyway
        ("hello", False),
        ("motorcar insurance cost", False),      # real question
        ("2000000", False),                      # payment/premium amount
        ("100000", False),
        ("what is serenicare", False),
        ("a", False),                            # too short
        ("", False),
    ],
)
def test_looks_like_noise(message, expected):
    assert _looks_like_noise(message) is expected


# --------------------------------------------------------------------------- #
# Gemini empty-.text recovery (generate.py)
# --------------------------------------------------------------------------- #
def test_extract_response_uses_text_when_present():
    gen = MiaGenerator.__new__(MiaGenerator)
    gen.provider = "gemini"
    resp = _FakeResponse(text="Hello there")
    text, _ = gen._extract_response(resp)
    assert text == "Hello there"


def test_gemini_parts_recovers_text_from_later_candidate():
    """A 200 response with empty .text but a text-bearing later candidate must
    yield usable text instead of being treated as empty output."""
    resp = _FakeResponse(
        text="",
        candidates=[
            _Candidate([_Part(text=None)]),             # e.g. a function_call part (no text)
            _Candidate([_Part(text="Here is the answer.")]),
        ],
    )
    parts = MiaGenerator._gemini_parts(resp)
    assert parts == ["Here is the answer."]


def test_gemini_parts_joins_multiple_text_parts():
    resp = _FakeResponse(
        text="",
        candidates=[
            _Candidate([_Part(text="Part one."), _Part(text="Part two.")]),
        ],
    )
    parts = MiaGenerator._gemini_parts(resp)
    assert parts == ["Part one.", "Part two."]


def test_gemini_parts_empty_when_no_text():
    resp = _FakeResponse(
        text="",
        candidates=[
            _Candidate([_Part(text=None), _Part(text="   ")]),
        ],
    )
    assert MiaGenerator._gemini_parts(resp) == []


def test_gemini_parts_skips_function_call_only_candidate():
    resp = _FakeResponse(
        text="",
        candidates=[
            _Candidate([_Part(text=None)]),  # function_call-only => no text
        ],
    )
    assert MiaGenerator._gemini_parts(resp) == []
