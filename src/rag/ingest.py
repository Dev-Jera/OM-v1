"""
Ingest processed chunks into the configured vector store (pgvector or Qdrant).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.rag_config_loader import RAGConfig

logger = logging.getLogger(__name__)


def _embedder_from_config(cfg: RAGConfig):
    from src.rag.embeddings.embedder import (
        GeminiEmbedder,
        OllamaEmbedder,
        OpenAIEmbedder,
        SentenceTransformersEmbedder,
    )

    p = cfg.embeddings.provider.lower()
    if p == "sentence_transformers":
        return SentenceTransformersEmbedder(model_name=cfg.embeddings.model)
    if p == "openai":
        return OpenAIEmbedder(model=cfg.embeddings.model)
    if p == "gemini":
        return GeminiEmbedder(
            model=cfg.embeddings.model,
            api_key_env=cfg.embeddings.api_key_env,
            output_dimensionality=cfg.embeddings.output_dimensionality,
        )
    if p == "ollama":
        return OllamaEmbedder(model=cfg.embeddings.model, base_url=cfg.embeddings.base_url or "http://localhost:11434")
    raise ValueError(f"Unknown embeddings provider: {cfg.embeddings.provider}")


def _vector_store_from_config(cfg: RAGConfig):
    from src.rag.integrations.pgvector_store import PgVectorStore
    from src.rag.integrations.qdrant_store import QdrantVectorStore

    p = cfg.vector_store.provider.lower()
    coll = cfg.vector_store.collection or "old_mutual_chunks"
    if p == "pgvector":
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL is required when vector_store.provider is pgvector")
        return PgVectorStore(table_name=coll, connection_string=url)
    if p in ("qdrant_local", "qdrant_http"):
        path = (cfg.vector_store.path or "data/qdrant") if p == "qdrant_local" else None
        host = cfg.vector_store.host or "localhost"
        port = cfg.vector_store.port or 6333
        if path:
            return QdrantVectorStore.from_local_path(collection=coll, path=path)
        return QdrantVectorStore.from_http(collection=coll, host=host, port=port)
    raise ValueError(f"Unknown vector_store.provider: {cfg.vector_store.provider}")


def ingest_chunks_to_qdrant(
    chunks_file: Path,
    cfg: RAGConfig,
    *,
    limit: Optional[int] = None,
) -> int:
    """
    Load chunks from JSONL, embed, and upsert into the configured vector store
    (pgvector or Qdrant). Returns number of chunks written.
    """
    embedder = _embedder_from_config(cfg)
    store = _vector_store_from_config(cfg)

    rows: List[Dict[str, Any]] = []
    with open(chunks_file, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit is not None and i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning("Skip invalid JSON line %s: %s", i + 1, e)
                continue
            text = obj.get("text") or ""
            if not text:
                continue
            chunk_id = obj.get("id") or f"{obj.get('doc_id', 'doc')}_{i}"
            # Include text in payload so it can be retrieved during search
            payload = {k: v for k, v in obj.items() if v is not None}
            if "text" not in payload:
                payload["text"] = text
            rows.append({"id": chunk_id, "text": text, "payload": payload})

    if not rows:
        logger.warning("No chunks to ingest from %s", chunks_file)
        return 0

    texts = [r["text"] for r in rows]
    vectors = embedder.embed_texts(texts)
    ids = [r["id"] for r in rows]
    payloads = [r["payload"] for r in rows]

    store_class = type(store).__name__
    if store_class == "PgVectorStore":
        store.ensure_table(embedder.dim)
        store.upsert(ids=ids, vectors=vectors, payloads=payloads)
    else:
        store.ensure_collection(vector_size=embedder.dim)
        store.upsert(ids=ids, vectors=vectors, payloads=payloads)

    logger.info("Ingested %d chunks into %s (%s)", len(ids), cfg.vector_store.collection, store_class)
    return len(ids)
