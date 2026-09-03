#!/usr/bin/env python3
"""Delete every record from the Mia push modules for a clean start.

Sometimes the CRM modules hold stale/test data (orphaned conversations,
throwaway complaints, old KPI snapshots) and we want a clean slate. This
script lists (default) or deletes (``--delete --yes``) *all* records in the
selected modules.

Deletions go to the Zoho recycle bin (recoverable) and are batched at most
100 ids per call (handled by :meth:`ZohoCRMWriter.delete`).

Credentials come from the environment (ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET,
ZOHO_REFRESH_TOKEN, ZOHO_REGION). Pass ``--env`` to load them from a file,
matching ``run_zoho_metrics_push.py``.

Examples:
    # Show record counts per module (no deletes):
    python scripts/wipe_mia_modules.py --env .env --list
    python scripts/wipe_mia_modules.py --env .env --list --module MiaConversations

    # Delete every record from all modules (requires --yes):
    python scripts/wipe_mia_modules.py --env .env --delete --yes
    python scripts/wipe_mia_modules.py --env .env --delete --yes --module MiaConversations,MiaEscalations
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Module name allow-list. Only these may be wiped.
KNOWN_MODULES = [
    "MiaConversations",
    "MiaEscalations",
    "Mia_Complaint",
    "Mia_Product_Logs",
    "MiaVisitors",
    "Mia_Bot_Metrics",
]


def _token_manager():
    from src.integrations.zoho.oauth import ZohoTokenManager

    return ZohoTokenManager(
        client_id=os.environ["ZOHO_CLIENT_ID"],
        client_secret=os.environ["ZOHO_CLIENT_SECRET"],
        refresh_token=os.environ["ZOHO_REFRESH_TOKEN"],
        region=os.environ.get("ZOHO_REGION", "com"),
    )


def _fetch_record_ids(writer) -> list:
    """Fetch every record id in the module, paginated."""
    ids = []
    page = 1
    while True:
        resp = writer._request(
            "GET",
            f"{writer.token_manager.api_base_url}/crm/v2/{writer.module}",
            params={"page": str(page), "per_page": "200", "fields": "id"},
        )
        data = resp.get("data") or []
        ids.extend([str(r["id"]) for r in data if r.get("id")])
        if not resp.get("info", {}).get("more_records", False) or not data or page > 500:
            break
        page += 1
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List or delete every record in the Mia push modules"
    )
    parser.add_argument("--env", type=Path, default=None, help="Optional .env file with ZOHO_* credentials")
    parser.add_argument("--module", type=str, default=None, help="Comma-separated modules to affect (default: all known)")
    parser.add_argument("--list", dest="action", action="store_const", const="list", default="list", help="Only print counts (default)")
    parser.add_argument("--delete", dest="action", action="store_const", const="delete", help="Delete all records in the selected modules")
    parser.add_argument("--yes", action="store_true", help="Confirm a --delete (required)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.env:
        from dotenv import load_dotenv

        load_dotenv(args.env)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    log = logging.getLogger(__name__)

    for var in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN"):
        if not os.environ.get(var):
            log.error("%s is required in the environment (use --env or set it)", var)
            return 1

    if args.module:
        modules = [m.strip() for m in args.module.split(",") if m.strip()]
        unknown = [m for m in modules if m not in KNOWN_MODULES]
        if unknown:
            log.error("Unknown module(s): %s. Allowed: %s", ", ".join(unknown), ", ".join(KNOWN_MODULES))
            return 1
    else:
        modules = list(KNOWN_MODULES)

    if args.action == "delete" and not args.yes:
        log.error("--delete requires --yes to confirm")
        return 1

    from src.integrations.zoho.crm_writer import ZohoCRMWriter

    token_manager = _token_manager()

    for module in modules:
        writer = ZohoCRMWriter(token_manager, module)
        ids = _fetch_record_ids(writer)
        log.info("%s: %d record(s) to %s", module, len(ids), "DELETE" if args.action == "delete" else "list")
        if args.action == "delete" and ids:
            writer.delete(ids)
            log.info("%s: deleted %d record(s) (recycle bin)", module, len(ids))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
