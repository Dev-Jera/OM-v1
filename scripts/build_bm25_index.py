#!/usr/bin/env python3
"""Rebuild the BM25 keyword index from the processed KB chunks JSONL.

Used at container startup so hybrid retrieval works on fresh deployments,
even when the raw scrape/PDF data are not shipped in the image.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag.keyword_search import BM25KeywordSearch

logger = logging.getLogger(__name__)

CHUNKS_FILE = Path(__file__).resolve().parent.parent / "data" / "processed" / "website_chunks.jsonl"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    if not CHUNKS_FILE.exists():
        logger.warning("Chunks file not found: %s - skipping BM25 rebuild", CHUNKS_FILE)
        return 0
    bm25 = BM25KeywordSearch()
    indexed = bm25.build_index(CHUNKS_FILE)
    logger.info("BM25 index ready: %s chunks -> %s", indexed, bm25.index_path)
    return 0 if indexed > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
