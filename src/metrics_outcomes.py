"""Single source of truth for conversation outcomes.

Every conversation in a window is classified into EXACTLY ONE bucket so that
dashboard cards never double-count the same chat:

  bot_down   - the bot errored / was down (service_error event)
  escalated  - handed off to a human agent (escalation_confirmed event)
  resolved   - customer confirmed "yes" to the completion question
  unresolved - customer said "no", or the bot explicitly couldn't answer
  no_verdict - ended, but neither outcome nor escalation was recorded
  in_progress - started within the window but shows no terminal signal yet

All endpoints derive their KPIs from these buckets so numbers agree
everywhere.
"""

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

OUTCOME_RESOLVED = "resolved"
OUTCOME_UNRESOLVED = "unresolved"
OUTCOME_ESCALATED = "escalated"
OUTCOME_BOT_DOWN = "bot_down"
OUTCOME_NO_VERDICT = "no_verdict"
OUTCOME_IN_PROGRESS = "in_progress"

_PRIORITY = [
    OUTCOME_BOT_DOWN,
    OUTCOME_ESCALATED,
    OUTCOME_RESOLVED,
    OUTCOME_UNRESOLVED,
    OUTCOME_NO_VERDICT,
    OUTCOME_IN_PROGRESS,
]


def _coerce_outcome(raw: Any) -> float:
    """Accept both numeric (1.0/0.0, as the seeder writes) and worded
    ("resolved"/"unresolved", as the chat completion path writes) outcomes."""
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        pass
    text = str(raw or "").strip().lower()
    if text in {"resolved", "yes", "true", "y", "1"}:
        return 1.0
    return 0.0


def _event_outcome(ev: Any) -> Optional[str]:
    event_type = str(getattr(ev, "event_type", ""))
    if event_type == "service_error":
        return OUTCOME_BOT_DOWN
    if event_type == "escalation_confirmed":
        return OUTCOME_ESCALATED
    if event_type == "completion_confirmed":
        payload = getattr(ev, "payload", {}) or {}
        outcome = _coerce_outcome(payload.get("outcome", 0.0))
        return OUTCOME_RESOLVED if outcome >= 0.5 else OUTCOME_UNRESOLVED
    if event_type == "unanswered_question":
        return OUTCOME_UNRESOLVED
    return None


def compute_conversation_outcomes(
    db: Any,
    start: datetime,
    end: datetime,
    conversations: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Classify every conversation in [start, end) into exactly one outcome.

    Returns counts plus per-conversation detail so callers can slice by
    outcome without recomputing.
    """
    if conversations is None:
        conversations = db.list_conversations(start, end)

    events = db.list_conversation_events(start=start, end=end, limit=50000)
    by_conversation: Dict[str, List[Any]] = defaultdict(list)
    for ev in events:
        cid = str(getattr(ev, "conversation_id", "") or "")
        if cid:
            by_conversation[cid].append(ev)

    detail: Dict[str, str] = {}
    for conv in conversations:
        cid = str(getattr(conv, "id", ""))
        if not cid:
            continue
        signals = [o for o in (_event_outcome(ev) for ev in by_conversation.get(cid, [])) if o]
        has_session_end = any(
            str(getattr(ev, "event_type", "")) == "session_end"
            for ev in by_conversation.get(cid, [])
        )
        if not signals:
            outcome = OUTCOME_NO_VERDICT if has_session_end else OUTCOME_IN_PROGRESS
        else:
            outcome = next((o for o in _PRIORITY if o in signals), OUTCOME_NO_VERDICT)
        detail[cid] = outcome

    by_outcome = Counter(detail.values())
    total = len(detail)

    return {
        "total": total,
        "by_outcome": dict(by_outcome),
        "detail": detail,
        # Convenience accessors
        "resolved": by_outcome.get(OUTCOME_RESOLVED, 0),
        "unresolved": by_outcome.get(OUTCOME_UNRESOLVED, 0),
        "escalated": by_outcome.get(OUTCOME_ESCALATED, 0),
        "bot_down": by_outcome.get(OUTCOME_BOT_DOWN, 0),
        "no_verdict": by_outcome.get(OUTCOME_NO_VERDICT, 0),
        "in_progress": by_outcome.get(OUTCOME_IN_PROGRESS, 0),
        "verdict_total": sum(
            by_outcome.get(k, 0)
            for k in (OUTCOME_RESOLVED, OUTCOME_UNRESOLVED, OUTCOME_ESCALATED, OUTCOME_BOT_DOWN)
        ),
    }