"""
Keyword-based search using BM25 for hybrid RAG retrieval.
"""

from __future__ import annotations

import json
import logging
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional

from rank_bm25 import BM25Okapi
import re

from src.utils.synonym_expander import SynonymExpander

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> List[str]:
    """Simple tokenization for BM25."""
    # Convert to lowercase and split on whitespace/punctuation
    tokens = re.findall(r"\b\w+\b", text.lower())
    return tokens


class BM25KeywordSearch:
    """
    BM25-based keyword search index for chunks.
    """

    def __init__(self, index_path: Optional[Path] = None, use_synonyms: bool = True):
        self.bm25: Optional[BM25Okapi] = None
        self.chunk_ids: List[str] = []
        self.chunk_metadata: Dict[str, Dict[str, Any]] = {}
        self.index_path = index_path or Path("data/embeddings/bm25_index.pkl")
        self.synonym_expander = SynonymExpander() if use_synonyms else None

    def build_index(self, chunks_file: Path) -> int:
        """
        Build BM25 index from chunks JSONL file.

        Returns:
            Number of chunks indexed
        """
        logger.info("Building BM25 keyword search index from %s", chunks_file)

        texts: List[List[str]] = []
        chunk_ids: List[str] = []
        chunk_metadata: Dict[str, Dict[str, Any]] = {}

        with open(chunks_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    chunk_id = obj.get("id")
                    text = obj.get("text", "")

                    if not chunk_id or not text:
                        continue

                    # Tokenize text for BM25
                    tokens = _tokenize(text)
                    if not tokens:
                        continue

                    texts.append(tokens)
                    chunk_ids.append(chunk_id)

                    # Store metadata for later retrieval
                    chunk_metadata[chunk_id] = {
                        "text": text,
                        "doc_id": obj.get("doc_id"),
                        "type": obj.get("type"),
                        "chunk_type": obj.get("chunk_type"),
                        "url": obj.get("url"),
                        "title": obj.get("title"),
                        "category": obj.get("category"),
                        "subcategory": obj.get("subcategory"),
                        "section_heading": obj.get("section_heading"),
                    }
                except json.JSONDecodeError as e:
                    logger.warning("Skipping invalid JSON line: %s", e)
                    continue

        if not texts:
            logger.warning("No valid chunks found to index")
            return 0

        # Build BM25 index
        self.bm25 = BM25Okapi(texts)
        self.chunk_ids = chunk_ids
        self.chunk_metadata = chunk_metadata

        # Save index to disk
        self._save_index()

        logger.info("Built BM25 index with %d chunks", len(chunk_ids))
        return len(chunk_ids)

    def _save_index(self) -> None:
        """Save BM25 index to disk."""
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.index_path, "wb") as f:
            pickle.dump(
                {
                    "bm25": self.bm25,
                    "chunk_ids": self.chunk_ids,
                    "chunk_metadata": self.chunk_metadata,
                },
                f,
            )
        logger.info("Saved BM25 index to %s", self.index_path)

    def load_index(self) -> bool:
        """
        Load BM25 index from disk.

        Returns:
            True if index was loaded successfully, False otherwise
        """
        if not self.index_path.exists():
            logger.warning("BM25 index not found at %s", self.index_path)
            return False

        try:
            with open(self.index_path, "rb") as f:
                data = pickle.load(f)
                self.bm25 = data["bm25"]
                self.chunk_ids = data["chunk_ids"]
                self.chunk_metadata = data["chunk_metadata"]
            logger.info("Loaded BM25 index with %d chunks", len(self.chunk_ids))
            return True
        except Exception as e:
            logger.error("Failed to load BM25 index: %s", e)
            return False

    def search(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search using BM25 keyword matching.

        Args:
            query: Search query string
            top_k: Number of results to return
            filters: Optional filters (category, type, chunk_type, products)

        Returns:
            List of results with scores and payloads (same format as vector search)
        """
        if self.bm25 is None:
            logger.error("BM25 index not loaded. Call load_index() or build_index() first.")
            return []

        # Expand query with synonyms if enabled
        search_query = query
        if self.synonym_expander:
            search_query = self.synonym_expander.expand_query(query)

        # Tokenize expanded query
        query_tokens = _tokenize(search_query)
        if not query_tokens:
            return []

        # Get BM25 scores
        scores = self.bm25.get_scores(query_tokens)

        # Create results with chunk IDs and scores
        results: List[tuple[str, float]] = list(zip(self.chunk_ids, scores))
        results.sort(key=lambda x: x[1], reverse=True)

        # Apply filters if provided
        if filters:
            filtered_results = []
            for chunk_id, score in results:
                metadata = self.chunk_metadata.get(chunk_id, {})

                # Apply category filter
                if "category" in filters:
                    if metadata.get("category") != filters["category"]:
                        continue

                # Apply type filter
                if "type" in filters:
                    if metadata.get("type") != filters["type"]:
                        continue

                # Apply chunk_type filter
                if "chunk_type" in filters:
                    if metadata.get("chunk_type") != filters["chunk_type"]:
                        continue

                # Apply products filter
                if "products" in filters and filters["products"]:
                    doc_id = metadata.get("doc_id", "")
                    if doc_id not in filters["products"]:
                        continue

                filtered_results.append((chunk_id, score))
            results = filtered_results

        # Return top_k results in same format as vector search
        output: List[Dict[str, Any]] = []
        for chunk_id, score in results[:top_k]:
            metadata = self.chunk_metadata.get(chunk_id, {})
            output.append(
                {
                    "id": chunk_id,
                    "score": float(score),
                    "payload": {
                        "text": metadata.get("text", ""),
                        "doc_id": metadata.get("doc_id"),
                        "type": metadata.get("type"),
                        "chunk_type": metadata.get("chunk_type"),
                        "url": metadata.get("url"),
                        "title": metadata.get("title"),
                        "category": metadata.get("category"),
                        "subcategory": metadata.get("subcategory"),
                        "section_heading": metadata.get("section_heading"),
                    },
                }
            )

        return output
