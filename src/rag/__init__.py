"""
High-level RAG pipeline (ingestion + querying).

This package wires together:
- utils.rag_config_loader
- rag.embeddings
- rag.integrations (Qdrant)
- processed chunks produced by src.processors.website_processor
"""

from .ingest import ingest_chunks_to_qdrant
from .query import retrieve_context

__all__ = ["ingest_chunks_to_qdrant", "retrieve_context"]
