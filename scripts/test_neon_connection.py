#!/usr/bin/env python3
"""
Test connectivity to Neon (or any Postgres) and pgvector.
Checks DATABASE_URL and runs a minimal query + vector extension.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    if " " in url or url.strip() != url:
        print("DATABASE_URL should be only the URL (e.g. postgresql://...?sslmode=require), no extra quotes or 'psql'", file=sys.stderr)
        return 1
    try:
        import psycopg2
        conn = psycopg2.connect(url)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.commit()
        cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector';")
        if cur.fetchone():
            print("Neon/Postgres connection OK; pgvector extension available")
        else:
            print("Neon/Postgres connection OK; pgvector might need to be enabled in Neon dashboard")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Connection failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
