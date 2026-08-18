"""Shared insurance KPI computation.

Single source of truth for the Bot Impact KPI suite. Used by:
- the ``/api/v1/metrics/impact`` endpoint (admin dashboard)
- the daily Zoho CRM metrics push (``src/integrations/zoho/push_metrics.py``)

Keeping both callers on this one function guarantees the dashboard and the
CRM records can never drift apart.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


def compute_impact_metrics(
    db: Any,
    days: int = 30,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Insurance KPI suite for the "Bot Impact" dashboard section.

    Targets are the agreed business defaults:
      resolution >= 80%, fallback <= 15%, CSAT >= 4.2, latency < 8s,
      off-hours handled >= 60%, quote -> payment >= 20%.

    ``now`` lets callers compute a historical window (e.g. one specific day)
    instead of "up to this instant".
    """
    if now is None:
        now = datetime.utcnow()
    start = now - timedelta(days=days)

    def _avg(values: List[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    def _rate(num: int, denom: int) -> float:
        return round((num / denom) * 100, 2) if denom > 0 else 0.0

    def _safe_int(value: Any) -> int:
        try:
            parsed = int(value)
            return parsed if parsed >= 0 else 0
        except (TypeError, ValueError):
            return 0

    # ---- window metrics from the single outcome model ----
    from src.metrics_outcomes import compute_conversation_outcomes

    outcomes = compute_conversation_outcomes(db, start, now)
    conversations = outcomes["total"]
    resolved = outcomes["resolved"]
    unresolved = outcomes["unresolved"]
    escalations = outcomes["escalated"]
    bot_down = outcomes["bot_down"]
    no_verdict = outcomes["no_verdict"]
    verdict_total = resolved + unresolved + escalations + bot_down
    self_serve = max(conversations - escalations - bot_down, 0)

    # Strict resolution: only conversations with a clear verdict count.
    resolution_rate = _rate(resolved, verdict_total)
    # Self-serve: handled without a human and the bot was not down.
    self_serve_rate = _rate(self_serve, conversations)
    # "Could not answer" = unresolved (content gap); one conversation each.
    fallback_rate = _rate(unresolved, conversations)
    bot_down_rate = _rate(bot_down, conversations)

    # ---- latency (successful bot replies only; errors record no latency) ----
    latency_metrics = db.list_rag_metrics(
        start=start,
        end=now,
        metric_types=["response_latency"],
        limit=50000,
    )
    latency_values = [float(m.value) for m in latency_metrics]
    latency_seconds = _avg(latency_values)

    # ---- CSAT tied to a real conversation, split by outcome ----
    csat_events = db.list_conversation_events(
        start=start, end=now, event_type="csat", limit=5000
    )
    csat_ratings = []
    csat_resolved_ratings = []
    csat_escalated_ratings = []
    for ev in csat_events:
        rating = float((ev.payload or {}).get("rating", 0))
        if rating <= 0:
            continue
        outcome = outcomes["detail"].get(str(getattr(ev, "conversation_id", "") or ""))
        if outcome is None:
            continue  # orphan rating: not tied to a conversation in this window
        csat_ratings.append(rating)
        if outcome == "resolved":
            csat_resolved_ratings.append(rating)
        elif outcome == "escalated":
            csat_escalated_ratings.append(rating)
    csat = _avg(csat_ratings)
    csat_resolved = _avg(csat_resolved_ratings)
    csat_escalated = _avg(csat_escalated_ratings)

    # ---- off-hours handling (business hours Mon-Fri 08:00-17:00 Kampala = UTC+3) ----
    conversation_rows = db.list_conversations(start, now)

    def _is_off_hours(dt: datetime) -> bool:
        local = dt + timedelta(hours=3)
        if local.weekday() >= 5:
            return True
        return local.hour < 8 or local.hour >= 17

    off_hours_total = 0
    off_hours_handled = 0
    for conv in conversation_rows:
        created = getattr(conv, "created_at", None)
        if created is None or not _is_off_hours(created):
            continue
        off_hours_total += 1
        outcome = outcomes["detail"].get(str(getattr(conv, "id", "") or ""))
        if outcome not in ("escalated", "bot_down"):
            off_hours_handled += 1
    off_hours_rate = _rate(off_hours_handled, off_hours_total)

    # ---- quote -> payment conversion ----
    try:
        quotes_created = _safe_int(db.count_quotes(start, now))
    except Exception:
        quotes_created = 0
    paid = _safe_int(
        db.count_payment_transactions(
            start, now, ["SUCCESS", "COMPLETED", "PAID", "payment_initiated"]
        )
    )
    quote_to_payment_rate = _rate(paid, quotes_created)

    # ---- effort hours saved (fact + clearly-labelled estimate) ----
    effort_minutes_per_conversation = float(
        os.getenv("EFFORT_MINUTES_PER_CONVERSATION", "4")
    )
    effort_hours_saved = round(self_serve * effort_minutes_per_conversation / 60.0, 2)

    # ---- repeat users (Zoho contact identity when linked, else phone) ----
    users_by_id = {str(u.id): u for u in db.list_users()}
    user_counts: Dict[str, int] = defaultdict(int)
    zoho_linked = 0
    for conv in conversation_rows:
        uid = str(getattr(conv, "user_id", "") or "")
        if not uid:
            continue
        user = users_by_id.get(uid)
        contact_id = str(getattr(user, "zoho_contact_id", "") or "") if user else ""
        key = contact_id if contact_id else uid
        user_counts[key] += 1
        if contact_id:
            zoho_linked += 1
    active_users = len(user_counts)
    repeat_users = sum(1 for count in user_counts.values() if count >= 2)
    repeat_user_rate = _rate(repeat_users, active_users)
    repeat_basis = "zoho-contact" if zoho_linked else "phone-based"

    targets = {
        "resolution_rate": 80.0,
        "self_serve_rate": 80.0,
        "fallback_rate": 15.0,
        "csat": 4.2,
        "latency_seconds": 8.0,
        "off_hours_rate": 60.0,
        "quote_to_payment_rate": 20.0,
        "bot_down_rate": 5.0,
    }

    def _kpi(key: str, label: str, value: float, unit: str) -> Dict[str, Any]:
        target = targets[key]
        met = bool(value >= target) if unit != "pct_dn" else bool(value <= target)
        return {
            "key": key,
            "label": label,
            "value": value,
            "target": target,
            "met": met,
            "unit": unit,
        }

    return {
        "window": {
            "days": days,
            "conversations": conversations,
            "escalations": escalations,
            "botDown": bot_down,
            "noVerdict": no_verdict,
        },
        "kpis": [
            _kpi("resolution_rate", "AI Resolution (strict)", resolution_rate, "pct"),
            _kpi("self_serve_rate", "Handled Without Agent", self_serve_rate, "pct"),
            _kpi("fallback_rate", "Could Not Answer", fallback_rate, "pct_dn"),
            _kpi("bot_down_rate", "Bot Down / Errors", bot_down_rate, "pct_dn"),
            _kpi("csat", "CSAT (avg rating)", csat, "rating"),
            _kpi("latency_seconds", "Avg Bot Latency", latency_seconds, "seconds"),
            _kpi("off_hours_rate", "Off-Hours Handled", off_hours_rate, "pct"),
            _kpi("quote_to_payment_rate", "Quote -> Payment", quote_to_payment_rate, "pct"),
        ],
        "resolution": {
            "strict": resolution_rate,
            "selfServe": self_serve_rate,
            "resolved": resolved,
            "unresolved": unresolved,
            "escalated": escalations,
            "botDown": bot_down,
            "noVerdict": no_verdict,
            "inProgress": outcomes["in_progress"],
            "verdictTotal": verdict_total,
            "target": targets["resolution_rate"],
            "basis": "Strict = confirmed 'yes' out of conversations with a verdict. "
            "Self-serve = handled without an agent (and bot not down). "
            "Chats with no outcome recorded are shown separately, not counted.",
        },
        "csat": {
            "value": csat,
            "responses": len(csat_ratings),
            "resolved": csat_resolved,
            "escalated": csat_escalated,
            "target": targets["csat"],
            "basis": "Only ratings tied to a conversation in this window.",
        },
        "latency": {"value": latency_seconds, "target": targets["latency_seconds"], "basis": "Successful bot replies only; errors record no latency."},
        "offHours": {
            "total": off_hours_total,
            "handled": off_hours_handled,
            "rate": off_hours_rate,
            "target": targets["off_hours_rate"],
            "businessHours": "Mon-Fri 08:00-17:00 Kampala (UTC+3)",
            "basis": "Handled = not escalated and bot not down.",
        },
        "quoteToPayment": {
            "quotes": quotes_created,
            "paid": paid,
            "rate": quote_to_payment_rate,
            "target": targets["quote_to_payment_rate"],
        },
        "effortHoursSaved": {
            "hours": effort_hours_saved,
            "chats": self_serve,
            "minutesPerConversation": effort_minutes_per_conversation,
            "basis": "estimated",
            "scope": "Estimate = chats handled without an agent x "
            f"{effort_minutes_per_conversation:.0f} min each. The minutes-per-chat "
            "assumption is adjustable; switch to 'measured' once real agent "
            "timing data is available.",
        },
        "repeatUsers": {
            "activeUsers": active_users,
            "repeatUsers": repeat_users,
            "repeatRate": repeat_user_rate,
            "zohoLinked": zoho_linked,
            "basis": repeat_basis,
            "note": "Repeat detection keys on the Zoho contact id when a user is "
            "linked; otherwise it falls back to the user id/phone.",
        },
        "targets": targets,
    }
