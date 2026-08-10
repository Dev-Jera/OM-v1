"""
Reply-safety helpers shared by the conversational brain and the RAG fallback.

These are post-processing guardrails, not a substitute for prompt hardening:

- ``looks_truncated`` / ``merge_continuation`` detect and repair replies that
  the LLM cut off at the token budget.
- ``strip_meta_lead_in`` removes sentences that leak retrieval mechanics
  ("Our available information doesn't specifically detail..."), plus a dangling
  connector left behind ("... However"), so a slipped reply never reads like a
  search result and never ends mid-thought.
"""

from __future__ import annotations

import re

# Connectors that, as a final bare word, signal an unfinished sentence.
DANGLING_WORDS = frozenset(
    {
        "a", "an", "and", "as", "at", "because", "but", "for", "from",
        "however", "therefore", "hence", "although", "while", "though",
        "since", "in", "into", "of", "on", "or", "that", "the", "to",
        "with", "which",
    }
)

_END_DANGLING_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(DANGLING_WORDS, key=len, reverse=True)) + r")\s*$",
    re.IGNORECASE,
)

# Connectors that open the sentence which followed a removed leak sentence.
_START_CONNECTOR_RE = re.compile(
    r"^(however|but|that said|that being said|although|while|though|because|"
    r"yet|additionally|moreover)\b[,\s]*",
    re.IGNORECASE,
)

# Distinctive retrieval-mechanics phrases. Any sentence containing one of these
# is dropped as a leak; these are never legitimate insider phrasing.
_LEAK_PHRASE_RE = re.compile(
    r"\b(available information|available data|retrieved information|retrieved data|"
    r"search results?|retrieved results?)\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def looks_truncated(text: str) -> bool:
    """Heuristic check for an answer cut off before it finished a thought."""
    s = (text or "").strip()
    if not s:
        return True

    # Very short replies can naturally end without punctuation.
    if len(s) < 80:
        return False

    if s.endswith((".", "!", "?", '"', "'", "*", ")", "]")):
        return False

    last_word = s.split()[-1].strip(".,!?;:'\")]").lower()
    if last_word in DANGLING_WORDS:
        return True

    # Unbalanced markdown bold is a strong signal of a cut-off answer.
    if s.count("**") % 2 == 1:
        return True

    return False


def merge_continuation(base_text: str, continuation_text: str) -> str:
    """Stitch a continuation reply onto a truncated base, avoiding repetition."""
    base = (base_text or "").rstrip()
    cont = (continuation_text or "").strip()
    if not cont:
        return base

    if cont.lower() in base.lower():
        return base

    # Remove simple overlap when continuation starts by repeating the tail.
    max_overlap = min(80, len(base), len(cont))
    overlap = 0
    for size in range(max_overlap, 11, -1):
        if base[-size:].lower() == cont[:size].lower():
            overlap = size
            break

    if overlap > 0:
        cont = cont[overlap:].lstrip()

    if not cont:
        return base

    separator = " " if base and base[-1].isalnum() and cont[0].isalnum() else ""
    return f"{base}{separator}{cont}"


def strip_meta_lead_in(text: str) -> str:
    """
    Remove sentences that leak retrieval mechanics.

    Drops any sentence mentioning "available information", "retrieved data",
    "search results", etc., and then clears a dangling connector left at the
    end ("... However") or at the start of what followed the removed sentence.

    Conservative: if nothing meaningful remains, the original reply is kept.
    """
    s = (text or "").strip()
    if not s:
        return s

    original = s
    sentences = [seg.strip() for seg in _SENTENCE_SPLIT_RE.split(s) if seg.strip()]

    kept = [seg for seg in sentences if not _LEAK_PHRASE_RE.search(seg)]
    if len(kept) == len(sentences):
        return original

    # A bare trailing connector ("... However") is a truncation signature; drop it.
    if kept and _END_DANGLING_RE.search(kept[-1]):
        kept[-1] = _END_DANGLING_RE.sub("", kept[-1]).rstrip()
        if not kept[-1]:
            kept.pop()

    result = " ".join(kept).strip()
    if not result:
        return original

    # The connector that once opened the sentence after the leak now leads the reply.
    result = _START_CONNECTOR_RE.sub("", result, count=1).strip()
    if not result:
        return original
    if result[:1].islower():
        result = result[0].upper() + result[1:]

    return result
