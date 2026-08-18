"""Conversation path attribution.

Each conversation is labelled by the style of its FIRST interaction:
  guided_flow  - user started through a guided form flow / "get a quote"
  direct_agent - user immediately requested a human agent
  freeform     - user chatted freely with the bot

Only the first recorded path for a conversation is kept so that metric
counts are consistent (one path per conversation).
"""

from datetime import datetime
from typing import Any, Optional

PATHS = ("guided_flow", "direct_agent", "freeform")

_WIDE_START = datetime(1970, 1, 1)
_WIDE_END = datetime(2999, 12, 31)


def record_conversation_path(
    db: Any,
    conversation_id: Optional[str],
    path: str,
    source: str,
) -> None:
    if db is None or not conversation_id or path not in PATHS:
        return
    try:
        existing = db.list_conversation_events(
            start=_WIDE_START,
            end=_WIDE_END,
            event_type="conversation_path",
            limit=1,
        )
        if existing:
            return
        db.add_conversation_event(
            conversation_id=conversation_id,
            event_type="conversation_path",
            payload={"path": path, "source": source},
        )
    except Exception:
        pass
