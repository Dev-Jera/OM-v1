#!/usr/bin/env python3
"""Create the Zoho CRM custom modules used by the KPI push and escalation handoff.

Creates (idempotently):
  - Mia_Bot_Metrics   : one record per day of Bot Impact KPIs
  - Mia_Escalations   : one record per bot escalation (transcript included)

Requires a refresh token whose consent included ZohoCRM.settings.modules.CREATE
(re-run scripts/zoho_oauth_setup.py --env .env --write after any scope change).

If your CRM edition does not allow API module creation, the script prints the
exact field list so the modules can be created in the CRM UI instead.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.integrations.zoho.oauth import ZohoTokenManager  # noqa: E402

METRICS_MODULE = {
    "module_name": "Mia_Bot_Metrics",
    "singular_label": "Mia Bot Metric",
    "plural_label": "Mia Bot Metrics",
    "fields": [
        {"field_label": "Name", "data_type": "text", "length": 255},
        {"field_label": "Metric Date", "data_type": "date", "length": 20},
        {"field_label": "Conversations", "data_type": "integer", "length": 16},
        {"field_label": "Resolved", "data_type": "integer", "length": 16},
        {"field_label": "Escalated", "data_type": "integer", "length": 16},
        {"field_label": "Could Not Answer", "data_type": "integer", "length": 16},
        {"field_label": "Bot Down", "data_type": "integer", "length": 16},
        {"field_label": "Resolution Rate", "data_type": "percent", "length": 20},
        {"field_label": "Self Serve Rate", "data_type": "percent", "length": 20},
        {"field_label": "Fallback Rate", "data_type": "percent", "length": 20},
        {"field_label": "Bot Down Rate", "data_type": "percent", "length": 20},
        {"field_label": "Off Hours Rate", "data_type": "percent", "length": 20},
        {"field_label": "Quote to Payment Rate", "data_type": "percent", "length": 20},
        {"field_label": "Repeat User Rate", "data_type": "percent", "length": 20},
        {"field_label": "CSAT", "data_type": "double", "length": 20},
        {"field_label": "Avg Latency Seconds", "data_type": "double", "length": 20},
        {"field_label": "Effort Hours Saved", "data_type": "double", "length": 20},
    ],
}

ESCALATIONS_MODULE = {
    "module_name": "Mia_Escalations",
    "singular_label": "Mia Escalation",
    "plural_label": "Mia Escalations",
    "fields": [
        {"field_label": "Name", "data_type": "text", "length": 255},
        {"field_label": "Escalated At", "data_type": "datetime", "length": 20},
        {"field_label": "Conversation ID", "data_type": "text", "length": 64},
        {"field_label": "Session ID", "data_type": "text", "length": 128},
        {"field_label": "Reason", "data_type": "text", "length": 255},
        {"field_label": "Customer Name", "data_type": "text", "length": 120},
        {"field_label": "Phone", "data_type": "phone", "length": 32},
        {"field_label": "Zoho Contact Id", "data_type": "text", "length": 64},
        {"field_label": "Transcript", "data_type": "textarea", "length": 32000},
        {
            "field_label": "Status",
            "data_type": "picklist",
            "pick_list_values": [
                {"display_value": "New", "actual_value": "New"},
                {"display_value": "In Progress", "actual_value": "In Progress"},
                {"display_value": "Closed", "actual_value": "Closed"},
            ],
        },
    ],
}

# CRM field API names are derived from labels (spaces -> underscores).
# These are the names the push code writes to.
FIELD_API_NAMES = {
    "Mia_Bot_Metrics": [
        "Name", "Metric_Date", "Conversations", "Resolved", "Escalated", "Could_Not_Answer",
        "Bot_Down", "Resolution_Rate", "Self_Serve_Rate", "Fallback_Rate",
        "Bot_Down_Rate", "Off_Hours_Rate", "Quote_to_Payment_Rate",
        "Repeat_User_Rate", "CSAT", "Avg_Latency_Seconds", "Effort_Hours_Saved",
    ],
    "Mia_Escalations": [
        "Name", "Escalated_At", "Conversation_ID", "Session_ID", "Reason", "Customer_Name",
        "Phone", "Zoho_Contact_Id", "Transcript", "Status",
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create Mia_Bot_Metrics and Mia_Escalations modules in Zoho CRM")
    parser.add_argument("--env", type=Path, default=None, help=".env file with ZOHO_* credentials")
    parser.add_argument("--only", choices=["metrics", "escalations"], default=None, help="Create only one of the modules")
    args = parser.parse_args()

    if args.env:
        from dotenv import load_dotenv

        load_dotenv(args.env)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    log = logging.getLogger("zoho_create_modules")

    import requests

    client_id = os.getenv("ZOHO_CLIENT_ID", "").strip()
    client_secret = os.getenv("ZOHO_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("ZOHO_REFRESH_TOKEN", "").strip()
    if not client_id or not client_secret or not refresh_token:
        log.error("ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET and ZOHO_REFRESH_TOKEN must be set")
        return 1

    token_manager = ZohoTokenManager(client_id, client_secret, refresh_token, region=os.getenv("ZOHO_REGION", "com").strip().lower())
    url = f"{token_manager.api_base_url}/crm/v2/settings/modules"

    modules = []
    if args.only in (None, "metrics"):
        modules.append(METRICS_MODULE)
    if args.only in (None, "escalations"):
        modules.append(ESCALATIONS_MODULE)

    failures = 0
    for module in modules:
        headers = {
            "Authorization": f"Zoho-oauthtoken {token_manager.get_access_token()}",
            "Content-Type": "application/json",
        }
        resp = requests.post(url, json={"modules": [module]}, headers=headers, timeout=60)
        if resp.status_code < 400:
            log.info("Created module %s", module["module_name"])
        else:
            failures += 1
            body = resp.text[:500]
            log.error("Could not create %s (HTTP %s): %s", module["module_name"], resp.status_code, body)
            if "already" in body.lower() or "duplicate" in body.lower():
                log.info("Module likely already exists — safe to continue.")
            else:
                log.info(
                    "Manual fallback — create module %s in the CRM UI with fields: %s",
                    module["module_name"],
                    ", ".join(f["field_label"] for f in module["fields"]),
                )

    for name, fields in FIELD_API_NAMES.items():
        log.info("Expected field API names for %s: %s", name, ", ".join(fields))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
