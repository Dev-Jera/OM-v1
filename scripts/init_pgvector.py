#!/usr/bin/env python3
"""
Ensure pgvector extension and RAG chunks table exist in the database.
Uses DATABASE_URL from environment. Run after Neon (or any Postgres) is provisioned.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import psycopg2


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    # Some hosts (e.g. Neon) add 'sslmode=require' via URL params
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    # Table creation is done by PgVectorStore.ensure_table when you run ingest.
    # This script only ensures the extension exists.
    cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector';")
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        print(f"pgvector extension ready (version {row[0]})")
    else:
        print("pgvector extension created")
    return 0


if __name__ == "__main__":
    sys.exit(main())
