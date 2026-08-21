"""Tests for follow-up detection and history-aware retrieval query augmentation.

Covers the fix for: a clarification question like "what do you mean safty net"
must be recognized as a follow-up, and the retrieval query must include the
assistant's previous answer (where the referenced phrase actually came from).
"""

import pytest

from src.chatbot.modes.conversational import (
    _augment_query_with_history,
    _is_followup_message,
    _last_assistant_turn,
    _last_user_turn,
)


HISTORY = [
    {"role": "user", "content": "could you define insurance for me?"},
    {
        "role": "assistant",
        "content": (
            "Insurance is a financial safety net that protects you or your business "
            "from unexpected losses. At Old Mutual, we offer tailored solutions."
        ),
    },
]


class TestIsFollowupMessage:
    @pytest.mark.parametrize(
        "message",
        [
            "what do you mean safty net",
            "What do you mean by safety net?",
            "what did you mean by PTD?",
            "what does comprehensive cover mean?",
            "What is meant by underwriting?",
            "the meaning of premium holiday",
            "can you explain that in simple terms?",
            "could you explain how claims work?",
            "explain waiting periods",
            "please clarify the exclusions",
            "can you elaborate on that?",
            "I don't understand",
            "i dont understand this",
            "in other words, what is it?",
        ],
    )
    def test_clarification_questions_are_followups(self, message):
        assert _is_followup_message(message) is True

    @pytest.mark.parametrize(
        "message",
        [
            "define insurance for me",
            "how do I file a claim?",
            "hello",
            "hi there",
            "",
            "   ",
        ],
    )
    def test_non_followups_unchanged(self, message):
        assert _is_followup_message(message) is False


class TestLastTurns:
    def test_last_user_turn(self):
        assert _last_user_turn(HISTORY) == "could you define insurance for me?"

    def test_last_assistant_turn(self):
        turn = _last_assistant_turn(HISTORY)
        assert turn is not None
        assert "safety net" in turn

    def test_missing_roles_return_none(self):
        assert _last_user_turn([]) is None
        assert _last_assistant_turn([]) is None
        assert _last_assistant_turn([{"role": "user", "content": "hi"}]) is None


class TestAugmentQueryWithHistory:
    def test_includes_both_user_and_assistant_context(self):
        augmented = _augment_query_with_history("what do you mean safty net", HISTORY, use_history=True)
        assert "user previously asked: could you define insurance for me?" in augmented
        assert "assistant answered:" in augmented
        assert "safety net" in augmented  # correctly spelled, from Mia's own words
        assert "Follow-up question: what do you mean safty net" in augmented

    def test_assistant_answer_truncated_to_400_chars(self):
        long_history = [
            {"role": "user", "content": "tell me about products"},
            {"role": "assistant", "content": "x" * 2000},
        ]
        augmented = _augment_query_with_history("tell me more", long_history, use_history=True)
        start = augmented.index("assistant answered: ") + len("assistant answered: ")
        end = augmented.index(". Follow-up question:")
        assistant_part = augmented[start:end]
        assert len(assistant_part) <= 400
        assert assistant_part.endswith("...")

    def test_use_history_false_returns_message_unchanged(self):
        message = "what do you mean safty net"
        assert _augment_query_with_history(message, HISTORY, use_history=False) == message

    def test_empty_history_returns_message_unchanged(self):
        message = "tell me more"
        assert _augment_query_with_history(message, [], use_history=True) == message

    def test_repeated_question_not_augmented(self):
        message = "Could you define insurance for me?"
        assert _augment_query_with_history(message, HISTORY, use_history=True) == message
