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
from src.rag.ingest import ingest_chunks_to_qdrant
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

