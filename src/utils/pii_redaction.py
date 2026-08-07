"""
PII redaction utilities.

Masks structured personal identifiers (phone numbers, emails, Ugandan national
IDs / passport numbers, long digit runs) before free-text chat messages are
sent to the LLM or persisted in the database.

NOTE: Personal information entered through the guided quote forms is business
data that is required to process an application and is intentionally NOT
redacted here. This module only protects free-text chat messages and the
conversation history that is assembled for the LLM.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PHONE_MASK = "[PHONE]"
EMAIL_MASK = "[EMAIL]"
ID_MASK = "[ID_NUMBER]"
DIGITS_MASK = "[NUMBER]"

# Email: standard shape, e.g. someone@example.co.ug
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Ugandan phone numbers:
#   +256 701 234 567 / +256701234567
#   0771 234 567 / 0771234567 / 0414 12 3456 (landline)
_PHONE_RE = re.compile(
    r"(?:\+256[\s\-]?\d{3}[\s\-]?\d{3}[\s\-]?\d{3}|"
    r"\+256\d{9}|"
    r"0[0-8]\d{8}|"
    r"0[0-8]\d{2}[\s\-]?\d{3}[\s\-]?\d{3})"
)

# Ugandan national ID / NIN: 2 letters + 10 digits + 2 letters, e.g. CF1234567890XY
_NIN_RE = re.compile(r"\b[A-Z]{2}\d{10}[A-Z]{2}\b")

# Passport-style numbers: one letter followed by 7-8 digits, e.g. B1234567
_PASSPORT_RE = re.compile(r"\b[A-Z]\d{7,8}\b")

# Generic long digit runs: account / card / reference numbers (8+ digits)
_LONG_DIGITS_RE = re.compile(r"(?<!\d)\d{8,}(?!\d)")

# Patterns applied in order. Placeholder masks never match any later pattern
# (they contain no digits), so masking is safe to run sequentially.
_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (_EMAIL_RE, EMAIL_MASK),
    (_PHONE_RE, PHONE_MASK),
    (_NIN_RE, ID_MASK),
    (_PASSPORT_RE, ID_MASK),
    (_LONG_DIGITS_RE, DIGITS_MASK),
]


def redaction_enabled() -> bool:
    """Return True when free-text PII redaction is enabled (default on)."""
    raw = (os.getenv("PII_REDACTION_ENABLED") or "").strip().lower()
    if not raw:
        return True
    return raw in {"1", "true", "yes", "on"}


def redact_text(text: Any) -> Tuple[str, Dict[str, int]]:
    """
    Mask personal identifiers in ``text``.

    Returns ``(masked_text, counts)`` where counts maps mask label -> number of
    replacements performed. Passing ``None`` yields ``("", {})``.
    """
    if text is None:
        return "", {}
    if not redaction_enabled():
        return str(text), {}

    value = str(text)
    counts: Dict[str, int] = {}
    for pattern, mask in _PATTERNS:
        if not value:
            break
        value, n = pattern.subn(mask, value)
        if n:
            counts[mask] = counts.get(mask, 0) + n
    return value, counts


def redact_message(message: Any) -> Dict[str, Any]:
    """Return a copy of a message dict with its content redacted."""
    if not isinstance(message, dict):
        return message
    content = str(message.get("content") or "")
    masked, _ = redact_text(content)
    return {**message, "content": masked}


def is_structured_payload(content: Any) -> bool:
    """
    Detect content that is a structured/form payload rather than natural chat.

    Form submissions are stored as human-readable key/value lists (e.g.
    "Submitted details:") as well as raw JSON. These may contain personal data
    and must never be assembled into LLM context.
    """
    if content is None:
        return True
    text = str(content).strip()
    if not text:
        return False

    lowered = text.lower()
    payload_prefixes = (
        "submitted details",
        "assistant update",
        "user form data",
        "user submitted",
    )
    if lowered.startswith(payload_prefixes):
        return True

    if text.startswith("{") and text.endswith("}"):
        return True
    if text.startswith("[") and text.endswith("]"):
        return True
    return False


def clean_history(messages: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """
    Filter conversation history for LLM consumption.

    - Drops entries that are structured/form payloads (may contain personal data).
    - Drops entries explicitly flagged as form_data in metadata.
    - Keeps only natural chat turns.
    """
    out: List[Dict[str, Any]] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        meta = msg.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        content = str(msg.get("content") or "")
        if not content.strip():
            continue
        if meta.get("form_data") or meta.get("structured"):
            continue
        if is_structured_payload(content):
            continue
        out.append(msg)
    return out


def redact_history(messages: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """Return a copy of history with each message content redacted."""
    return [redact_message(m) for m in (messages or [])]
