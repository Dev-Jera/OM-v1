#!/usr/bin/env python3
"""
Generate embeddings from processed chunks and store in the configured vector store (pgvector or Qdrant).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.utils.rag_config_loader import load_rag_config
from src.rag.ingest import _vector_store_from_config, ingest_chunks_to_qdrant
from src.rag.keyword_search import BM25KeywordSearch


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Embed processed chunks into configured vector store (pgvector or Qdrant)")
    parser.add_argument("--config", type=Path, default=None, help="Path to rag_config.yml (default: config/rag_config.yml)")
    parser.add_argument("--chunks-file", type=Path, default=Path("data/processed/website_chunks.jsonl"), help="Input chunks JSONL")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of chunks embedded (for quick tests)")
    args = parser.parse_args()

    load_dotenv()
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    cfg = load_rag_config(args.config)
    total = ingest_chunks_to_qdrant(args.chunks_file, cfg, limit=args.limit)
    logger.info("Embedded and stored %s chunks into %s collection '%s'", total, cfg.vector_store.provider, cfg.vector_store.collection)

    provider = (cfg.vector_store.provider or "").lower()
    if provider in ("qdrant_http", "qdrant_local") and args.limit is None:
        # Sync Qdrant to the chunks file: remove points that are no longer in the
        # file (stale website chunks from a previous scrape). Added PDF/text chunks
        # are still in the file, so they are kept.
        valid_ids: set[str] = set()
        with open(args.chunks_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                chunk_id = obj.get("id")
                if chunk_id:
                    valid_ids.add(str(chunk_id))
        store = _vector_store_from_config(cfg)
        removed = store.delete_stale_points(valid_ids)
        logger.info("Vector store synced to %s: removed %s stale chunk(s) no longer in %s", provider, removed, args.chunks_file)
    elif provider not in ("qdrant_http", "qdrant_local"):
        logger.info("Vector provider '%s' does not support sync cleanup; skipping stale-point removal", provider)

    # Also build BM25 keyword search index if hybrid search is enabled
    if cfg.retrieval.hybrid.enabled:
        logger.info("Building BM25 keyword search index...")
        keyword_search = BM25KeywordSearch()
        keyword_total = keyword_search.build_index(args.chunks_file)
        logger.info("Built BM25 index with %s chunks", keyword_total)
    else:
        logger.info("Hybrid search is disabled, skipping BM25 index build")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

