"""KPI push into the Zoho CRM ``Mia_Bot_Metrics`` module.

Daily + intraday (hourly) snapshots.

Uses the exact same KPI math as the ``/metrics/impact`` endpoint
(``src/metrics_kpis.py``) so the admin dashboard and the CRM records can
never drift apart.

- **Daily**: one record per day keyed by ``Metric_Date``; re-running a day
  upserts (updates) instead of duplicating. Window = that calendar day.
- **Hourly**: one record per day+hour keyed by ``Metric_Date`` +
  ``Metric_Hour``. Window = the rolling 24h ending at the top of that hour.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from src.integrations.zoho.crm_writer import ZohoCRMWriter
from src.integrations.zoho.oauth import ZohoTokenManager
from src.metrics_kpis import compute_impact_metrics

logger = logging.getLogger(__name__)

DEFAULT_MODULE = "Mia_Bot_Metrics"
DUPLICATE_CHECK_FIELDS = ["Metric_Date"]
DUPLICATE_CHECK_FIELDS_HOURLY = ["Metric_Date", "Metric_Hour"]


def impact_payload_to_crm_record(
    payload: Dict[str, Any],
    metric_date: str,
    metric_hour: Optional[int] = None,
) -> Dict[str, Any]:
    """Map the shared impact payload onto flat CRM fields."""
    kpis = {k["key"]: k["value"] for k in payload.get("kpis", [])}
    resolution = payload.get("resolution", {})
    name = f"{metric_date}-{metric_hour:02d}" if metric_hour is not None else metric_date
    record = {
        "Name": name,
        "Metric_Date": metric_date,
        "Conversations": payload.get("window", {}).get("conversations", 0),
        "Resolved": resolution.get("resolved", 0),
        "Escalated": resolution.get("escalated", 0),
        "Could_Not_Answer": resolution.get("unresolved", 0),
        "Bot_Down": resolution.get("botDown", 0),
        "Resolution_Rate": resolution.get("strict", 0.0),
        "Self_Serve_Rate": resolution.get("selfServe", 0.0),
        "Fallback_Rate": kpis.get("fallback_rate", 0.0),
        "Bot_Down_Rate": kpis.get("bot_down_rate", 0.0),
        "CSAT": payload.get("csat", {}).get("value", 0.0),
        "Avg_Latency_Seconds": payload.get("latency", {}).get("value", 0.0),
        "Off_Hours_Rate": payload.get("offHours", {}).get("rate", 0.0),
        "Effort_Hours_Saved": payload.get("effortHoursSaved", {}).get("hours", 0.0),
        "Repeat_User_Rate": payload.get("repeatUsers", {}).get("repeatRate", 0.0),
    }
    if metric_hour is not None:
        record["Metric_Hour"] = metric_hour
    return record


def _resolve_writer(
    module: Optional[str] = None,
    writer: Optional[ZohoCRMWriter] = None,
    token_manager: Optional[ZohoTokenManager] = None,
) -> ZohoCRMWriter:
    if writer is not None:
        return writer
    module = module or os.getenv("ZOHO_METRICS_MODULE", DEFAULT_MODULE)
    if token_manager is None:
        token_manager = ZohoTokenManager(
            os.getenv("ZOHO_CLIENT_ID", "").strip(),
            os.getenv("ZOHO_CLIENT_SECRET", "").strip(),
            os.getenv("ZOHO_REFRESH_TOKEN", "").strip(),
            region=os.getenv("ZOHO_REGION", "com").strip().lower(),
        )
    return ZohoCRMWriter(token_manager, module)


def push_hour(
    db: Any,
    hour: Optional[datetime] = None,
    module: Optional[str] = None,
    writer: Optional[ZohoCRMWriter] = None,
    token_manager: Optional[ZohoTokenManager] = None,
) -> Dict[str, Any]:
    """Compute and upsert an hourly intraday snapshot of the KPIs.

    Window = the rolling 24h ending at the top of ``hour`` (default: now, UTC).

    Returns ``{"date", "hour", "record", "response"}``.
    """
    if hour is None:
        hour = datetime.utcnow()
    hour = hour.replace(minute=0, second=0, microsecond=0)
    window_end = hour + timedelta(hours=1)
    payload = compute_impact_metrics(db, days=1, now=window_end)
    metric_date = window_end.strftime("%Y-%m-%d")
    record = impact_payload_to_crm_record(payload, metric_date, month_hour_index(hour))

    writer = _resolve_writer(module=module, writer=writer, token_manager=token_manager)
    response = writer.upsert([record], DUPLICATE_CHECK_FIELDS_HOURLY)
    logger.info(
        "Zoho metrics push: upserted hourly %s-%02d into %s",
        metric_date,
        month_hour_index(hour),
        writer.module,
    )
    return {"date": metric_date, "hour": month_hour_index(hour), "record": record, "response": response}


def month_hour_index(dt: datetime) -> int:
    """0-based hour-of-day index for a given datetime."""
    return dt.hour


def push_day(
    db: Any,
    day: Optional[datetime] = None,
    module: Optional[str] = None,
    writer: Optional[ZohoCRMWriter] = None,
    token_manager: Optional[ZohoTokenManager] = None,
) -> Dict[str, Any]:
    """Compute and upsert the KPI record for one day (default: today, UTC).

    Returns ``{"date", "record", "response"}``.
    """
    if day is None:
        day = datetime.utcnow()
    metric_date = day.strftime("%Y-%m-%d")
    # Window = [metric_date 00:00 UTC, metric_date+1 00:00 UTC)
    window_end = datetime(day.year, day.month, day.day) + timedelta(days=1)
    payload = compute_impact_metrics(db, days=1, now=window_end)
    record = impact_payload_to_crm_record(payload, metric_date)

    writer = _resolve_writer(module=module, writer=writer, token_manager=token_manager)
    response = writer.upsert([record], DUPLICATE_CHECK_FIELDS)
    logger.info("Zoho metrics push: upserted %s into %s", metric_date, writer.module)
    return {"date": metric_date, "record": record, "response": response}
