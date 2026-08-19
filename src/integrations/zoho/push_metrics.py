"""Daily KPI push into the Zoho CRM ``Mia_Bot_Metrics`` module.

Uses the exact same KPI math as the ``/metrics/impact`` endpoint
(``src/metrics_kpis.py``) so the admin dashboard and the CRM records can
never drift apart. Each day becomes ONE record keyed by ``Metric_Date``;
re-running a day upserts (updates) instead of duplicating.
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


def impact_payload_to_crm_record(payload: Dict[str, Any], metric_date: str) -> Dict[str, Any]:
    """Map the shared impact payload onto flat CRM fields."""
    kpis = {k["key"]: k["value"] for k in payload.get("kpis", [])}
    resolution = payload.get("resolution", {})
    return {
        "Name": metric_date,
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
        "Quote_to_Payment_Rate": payload.get("quoteToPayment", {}).get("rate", 0.0),
        "Effort_Hours_Saved": payload.get("effortHoursSaved", {}).get("hours", 0.0),
        "Repeat_User_Rate": payload.get("repeatUsers", {}).get("repeatRate", 0.0),
    }


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

    if writer is None:
        module = module or os.getenv("ZOHO_METRICS_MODULE", DEFAULT_MODULE)
        if token_manager is None:
            token_manager = ZohoTokenManager(
                os.getenv("ZOHO_CLIENT_ID", "").strip(),
                os.getenv("ZOHO_CLIENT_SECRET", "").strip(),
                os.getenv("ZOHO_REFRESH_TOKEN", "").strip(),
                region=os.getenv("ZOHO_REGION", "com").strip().lower(),
            )
        writer = ZohoCRMWriter(token_manager, module)

    response = writer.upsert([record], DUPLICATE_CHECK_FIELDS)
    logger.info("Zoho metrics push: upserted %s into %s", metric_date, writer.module)
    return {"date": metric_date, "record": record, "response": response}
