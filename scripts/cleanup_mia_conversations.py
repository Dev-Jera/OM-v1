#!/usr/bin/env python3
"""List and (optionally) delete orphaned records in the Zoho MiaConversations module.

An "orphan" is a Zoho ``MiaConversations`` record whose ``Conversation_ID`` has
no matching row in the local Postgres ``conversations`` table. These can pile up
from earlier builds/configuration mistakes. This script lets you inspect them
first (list-only, the default) and then purge them by Zoho record id.

The authoritative source of conversation ids is the local database (the same
Neon DB the hosted app uses), so we never delete a record that still has a real
conversation behind it. Deletions go to the Zoho recycle bin (recoverable).

Credentials come from the environment (ZOHO_* and DATABASE_URL). Pass ``--env``
to load them from a file, matching ``run_zoho_metrics_push.py``.

Examples:
    # Show orphans only (no deletes):
    python scripts/cleanup_mia_conversations.py --env .env
    python scripts/cleanup_mia_conversations.py --env .env --list

    # Purge every orphaned record (requires --yes):
    python scripts/cleanup_mia_conversations.py --env .env --delete --yes
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _all_conversation_ids(postgres_db) -> set:
    """Return the set of every conversation id present in the DB (authoritative)."""
    from sqlalchemy import select

    from src.database.models import Conversation

    ids = set()
    try:
        with postgres_db._session() as s:
            rows = s.execute(select(Conversation.id)).scalars().all()
            ids = {str(r) for r in rows if r is not None}
    except Exception as exc:  # noqa: BLE001 - surface cleanly
        raise RuntimeError(f"Could not read conversation ids from DB: {exc}") from exc
    return ids


def _fetch_module_records(writer) -> list:
    """Fetch every record (id + Conversation_ID) from the configured module."""
    records = []
    page = 1
    while True:
        url = f"{writer.token_manager.api_base_url}/crm/v2/{writer.module}"
        resp = writer._request(
            "GET",
            url,
            params={"page": str(page), "per_page": "200", "fields": "id,Name,Conversation_ID"},
        )
        data = resp.get("data") or []
        records.extend(data)
        more = resp.get("info", {}).get("more_records", False)
        if not more or not data or page > 500:
            break
        page += 1
    return records


def _build_db():
    from src.utils.runtime_env import should_use_real_postgres

    if should_use_real_postgres():
        from src.database.postgres_real import PostgresDB

        return PostgresDB(connection_string=os.environ["DATABASE_URL"])
    from src.database.postgres import PostgresDB

    return PostgresDB()


def _writer():
    from src.integrations.zoho.crm_writer import ZohoCRMWriter
    from src.integrations.zoho.oauth import ZohoTokenManager

    client_id = os.getenv("ZOHO_CLIENT_ID", "").strip()
    client_secret = os.getenv("ZOHO_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("ZOHO_REFRESH_TOKEN", "").strip()
    if not client_id or not client_secret or not refresh_token:
        raise RuntimeError("Missing ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET / ZOHO_REFRESH_TOKEN")
    module = os.getenv("ZOHO_CONVERSATION_MODULE", "MiaConversations").strip() or "MiaConversations"
    token_manager = ZohoTokenManager(
        client_id,
        client_secret,
        refresh_token,
        region=os.getenv("ZOHO_REGION", "com").strip().lower(),
    )
    return ZohoCRMWriter(token_manager, module)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List / delete orphaned Zoho MiaConversations records"
    )
    parser.add_argument("--env", type=Path, default=None, help="Optional .env file (ZOHO_* / DATABASE_URL credentials)")
    parser.add_argument(
        "--list",
        action="store_true",
        help="List orphaned records only (default; no deletes).",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Purge all orphaned records by Zoho record id.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required confirmation flag for --delete.",
    )
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

    if args.delete and not args.yes:
        log.error("--delete requires the --yes confirmation flag")
        return 1
    if not args.delete and not args.list:
        args.list = True

    db = _build_db()
    try:
        known_ids = _all_conversation_ids(db)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    log.info("DB has %d authoritative conversation ids", len(known_ids))

    try:
        writer = _writer()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1

    records = _fetch_module_records(writer)
    log.info("Fetched %d record(s) from module '%s'", len(records), writer.module)

    orphans = []
    for row in records:
        cid = str(row.get("Conversation_ID") or "").strip()
        zoho_id = str(row.get("id") or "").strip()
        if not cid or cid not in known_ids:
            orphans.append({"zoho_id": zoho_id, "conversation_id": cid, "name": row.get("Name")})

    if not orphans:
        log.info("No orphaned records found.")
        return 0

    log.warning("Found %d orphaned record(s):", len(orphans))
    for o in orphans:
        log.warning("  Zoho id=%s Conversation_ID=%r Name=%r", o["zoho_id"], o["conversation_id"], o.get("name"))

    if not args.delete:
        log.info("List-only mode: nothing deleted. Re-run with --delete --yes to purge.")
        return 0

    ids = [o["zoho_id"] for o in orphans if o["zoho_id"]]
    log.info("Deleting %d orphaned record(s) by id...", len(ids))
    try:
        writer.delete(ids)
    except Exception as exc:  # noqa: BLE001 - CLI surface
        log.error("Delete failed: %s: %s", type(exc).__name__, exc)
        return 1
    log.info("Done. Deleted records moved to the Zoho recycle bin (recoverable).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
