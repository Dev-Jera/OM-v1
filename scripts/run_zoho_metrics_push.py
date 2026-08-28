#!/usr/bin/env python3
"""Push one day of Bot Impact KPIs into the Zoho CRM ``Mia_Bot_Metrics`` module.

Uses the exact same KPI math as the ``/metrics/impact`` endpoint. The push is
an upsert keyed by ``Metric_Date`` — re-running a day updates the record
instead of duplicating it.

Credentials come from the environment (ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET,
ZOHO_REFRESH_TOKEN, ZOHO_REGION). Pass ``--env`` to load them from a file.

Examples:
    python scripts/run_zoho_metrics_push.py --env .env
    python scripts/run_zoho_metrics_push.py --env .env --date 2026-08-17
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _build_db():
    from src.utils.runtime_env import should_use_real_postgres

    if should_use_real_postgres():
        from src.database.postgres_real import PostgresDB

        return PostgresDB(connection_string=os.environ["DATABASE_URL"])
    from src.database.postgres import PostgresDB

    return PostgresDB()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Push one day of Bot Impact KPIs into Zoho CRM (Mia_Bot_Metrics)"
    )
    parser.add_argument("--env", type=Path, default=None, help="Optional .env file with ZOHO_* / DB credentials")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Day to push as YYYY-MM-DD (default: today UTC). Useful for backfill.",
    )
    parser.add_argument("--module", type=str, default=None, help="CRM module name (default: ZOHO_METRICS_MODULE or Mia_Bot_Metrics)")
    parser.add_argument(
        "--period",
        type=str,
        choices=["daily", "hourly"],
        default="daily",
        help="daily = one record per calendar day; hourly = rolling-24h snapshot for the current hour",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    if args.env:
        from dotenv import load_dotenv

        load_dotenv(args.env)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    log = logging.getLogger(__name__)

    day = None
    if args.date:
        try:
            day = datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            log.error("--date must be YYYY-MM-DD, got %r", args.date)
            return 1

    from src.integrations.zoho.push_metrics import push_day, push_hour

    try:
        db = _build_db()
        if args.period == "hourly":
            result = push_hour(db, module=args.module)
        else:
            result = push_day(db, day=day, module=args.module)
    except Exception as e:  # noqa: BLE001 - CLI surface
        log.error("%s: %s", type(e).__name__, e)
        return 1
    log.info(
        "Zoho metrics push complete for %s%s: %s conversations, resolution %s%%, csat %s",
        result["date"],
        f" hour {result.get('hour')}" if result.get("hour") is not None else "",
        result["record"].get("Conversations"),
        result["record"].get("Resolution_Rate"),
        result["record"].get("CSAT"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
