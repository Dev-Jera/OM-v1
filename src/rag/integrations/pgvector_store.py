"""
PgVector vector store for RAG (Neon/Postgres with pgvector extension).
"""

from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


def _normalize_connection_string(s: str) -> str:
    """Strip common mistakes: 'psql \'...\'', extra quotes, whitespace."""
    s = s.strip()
    # Remove leading "psql " or "psql'..." wrapper
    if re.match(r"^psql\s+", s, re.IGNORECASE):
        s = re.sub(r"^psql\s+", "", s, flags=re.IGNORECASE).strip()
    if s.startswith("'") and s.endswith("'"):
        s = s[1:-1].strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1].strip()
    return s


class PgVectorStore:
    """
    Vector store backed by Postgres + pgvector.
    Uses DATABASE_URL for connection; supports connection pooling and
    ensure_table, upsert, search (cosine similarity, optional metadata filters).
    """

    def __init__(
        self,
        *,
        table_name: str = "rag_chunks",
        connection_string: str,
        pool_size: int = 5,
    ) -> None:
        self.table_name = table_name
        self.connection_string = _normalize_connection_string(connection_string)
        # Single long-lived connection per process for RAG queries. This avoids the
        # overhead of establishing a new TCP/TLS connection to Postgres for every
        # search, while keeping the public API unchanged. If the connection is
        # closed or broken, it will be lazily re-created on next use.
        self._conn_obj: Optional[Any] = None
        self._pool: List[Any] = []  # kept for backward-compatibility; not used
        self._pool_size = pool_size

    @contextmanager
    def _conn(self):
        # Lazily create (or re-create) a single connection and reuse it across
        # calls. psycopg2 connections are not safe for concurrent use from
        # multiple threads, but in the typical FastAPI + uvicorn async setup
        # queries are executed sequentially in the same thread per process.
        if self._conn_obj is None or getattr(self._conn_obj, "closed", 0):
            self._conn_obj = psycopg2.connect(self.connection_string, cursor_factory=RealDictCursor)
        conn = self._conn_obj
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def ensure_table(self, vector_size: int) -> None:
        """Create table and enable pgvector extension if missing."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id TEXT PRIMARY KEY,
                        embedding vector(%s),
                        payload JSONB,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );
                    """,
                    (vector_size,),
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_{self.table_name.replace("-", "_")}_embedding
                    ON {self.table_name} USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100);
                    """
                )
        logger.info("Ensured table %s with vector size %s", self.table_name, vector_size)

    def upsert(
        self,
        *,
        ids: List[str],
        vectors: List[List[float]],
        payloads: List[Dict[str, Any]],
    ) -> None:
        """Insert or overwrite chunks by id."""
        if not ids or len(ids) != len(vectors) or len(ids) != len(payloads):
            raise ValueError("ids, vectors, payloads must be same length and non-empty")
        with self._conn() as conn:
            with conn.cursor() as cur:
                for i, (cid, vec, payload) in enumerate(zip(ids, vectors, payloads, strict=True)):
                    cur.execute(
                        f"""
                        INSERT INTO {self.table_name} (id, embedding, payload)
                        VALUES (%s, %s::vector, %s::jsonb)
                        ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding, payload = EXCLUDED.payload;
                        """,
                        (cid, vec, json.dumps(payload)),
                    )
        logger.debug("Upserted %d rows into %s", len(ids), self.table_name)

    def search(
        self,
        *,
        query_vector: List[float],
        limit: int = 8,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Cosine similarity search. filters keys are JSONB paths, e.g. type, chunk_type.
        Use filters["products"] = [doc_id, ...] to restrict to those doc_ids (matches payload->>'doc_id').
        Returns list of { "id", "score", "payload" }.
        """
        where_clauses: List[str] = []
        filter_params: List[Any] = []
        for k, v in (filters or {}).items():
            if v is None:
                continue
            if k == "products" and isinstance(v, (list, tuple)):
                if not v:
                    continue
                placeholders = ",".join(["%s"] * len(v))
                where_clauses.append(f"(payload->>'doc_id') IN ({placeholders})")
                filter_params.extend(v)
            else:
                where_clauses.append("payload->>%s = %s")
                filter_params.extend([k, str(v)])
        where_sql = " AND ".join(where_clauses) if where_clauses else ""

        # Params must match SQL %s order: SELECT vector, [WHERE params], ORDER vector, LIMIT
        exec_params: List[Any] = [query_vector] + filter_params + [query_vector, limit]

        sql = f"""
            SELECT id, payload, 1 - (embedding <=> %s::vector) AS score
            FROM {self.table_name}
            {"WHERE " + where_sql if where_sql else ""}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """

        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, exec_params)
                    rows = cur.fetchall()
        except Exception as e:
            err = str(e)
            if "different vector dimensions" in err or "dimension" in err.lower():
                raise RuntimeError(
                    f"Vector dimension mismatch: {err}. "
                    "Ensure the table was created and filled with the same embedding size as queries. "
                    "Run: python scripts/recreate_vector_table.py --yes && python scripts/generate_embeddings.py "
                    "(use the same DATABASE_URL as the app). If the app runs on Railway, redeploy after updating config."
                ) from e
            raise
        return [{"id": r["id"], "score": float(r["score"]), "payload": (r["payload"] or {})} for r in rows]

    def count(self) -> int:
        """Return number of rows in the table (for diagnostics when retrieval is empty)."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) AS n FROM {self.table_name}")
                row = cur.fetchone()
                return int(row["n"]) if row else 0
