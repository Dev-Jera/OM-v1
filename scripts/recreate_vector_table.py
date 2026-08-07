#!/usr/bin/env python3
"""
Drop the pgvector RAG table so it can be recreated with a new embedding dimension.

Run this when you switch embedders (e.g. from 384-dim sentence-transformers to
3072-dim gemini-embedding-001). Then re-run generate_embeddings.py to ingest again.

  python scripts/recreate_vector_table.py --yes
  python scripts/generate_embeddings.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

import psycopg2
from psycopg2 import sql


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Drop the pgvector RAG table so it can be recreated with a new embedding dimension."
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    parser.add_argument("--table", type=str, default=None, help="Table name (default: from config vector_store.collection)")
    parser.add_argument("--config", type=Path, default=None, help="Path to rag_config.yml")
    args = parser.parse_args()

    table_name = args.table
    if not table_name:
        from src.utils.rag_config_loader import load_rag_config

        cfg = load_rag_config(args.config)
        if cfg.vector_store.provider.lower() != "pgvector":
            print("Config vector_store.provider is not pgvector; nothing to drop.", file=sys.stderr)
            return 0
        table_name = cfg.vector_store.collection or "old_mutual_chunks"

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1

    if not args.yes:
        confirm = input(f"Drop table {table_name!r}? All vectors will be lost. [y/N]: ")
        if confirm.strip().lower() != "y":
            print("Aborted.")
            return 0

    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table_name)))
    cur.close()
    conn.close()
    print(f"Dropped table {table_name}. Run generate_embeddings.py to re-ingest with the current embedder.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
