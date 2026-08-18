#!/usr/bin/env python3
"""Sync Zoho CRM products into the RAG chunk pipeline.

Merges ``zoho:`` chunks into ``data/processed/website_chunks.jsonl`` and
product entries into ``data/processed/website_index.json``. The existing
``scripts/generate_embeddings.py`` step then embeds everything into the
configured vector store (Qdrant) as usual.

Credentials come from the environment (ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET,
ZOHO_REFRESH_TOKEN, ZOHO_REGION). Pass ``--env`` to load them from a file.

Safe to re-run: existing ``zoho:`` chunks are replaced, all other chunks are
kept byte-identical.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.integrations.zoho.sync import run_zoho_sync  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync Zoho CRM products into the RAG chunk pipeline"
    )
    parser.add_argument("--env", type=Path, default=None, help="Optional .env file with ZOHO_* credentials")
    parser.add_argument("--config", type=Path, default=None, help="Path to config/zoho_crm_fields.yml")
    parser.add_argument(
        "--chunks-file",
        type=Path,
        default=Path("data/processed/website_chunks.jsonl"),
        help="Chunks JSONL to merge into (default: data/processed/website_chunks.jsonl)",
    )
    parser.add_argument(
        "--index-file",
        type=Path,
        default=Path("data/processed/website_index.json"),
        help="Product index JSON to merge into (default: data/processed/website_index.json)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit number of product records pulled")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    try:
        result = run_zoho_sync(
            env_path=args.env,
            config_path=args.config,
            chunks_file=args.chunks_file,
            index_file=args.index_file,
            limit=args.limit,
        )
    except Exception as e:  # noqa: BLE001 - CLI surface
        logging.getLogger(__name__).error("%s: %s", type(e).__name__, e)
        return 1
    logging.getLogger(__name__).info(
        "Zoho sync complete: %s product(s) pulled, %s chunk(s) written "
        "(%s attached to existing products), %s stale zoho chunk(s) replaced",
        result.records,
        result.chunks,
        result.attached,
        result.replaced,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
