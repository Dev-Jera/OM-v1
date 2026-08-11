"""
Load and validate RAG configuration (embeddings, vector store, retrieval, generation).
Supports pgvector and Qdrant as vector store providers.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EmbeddingsConfig(BaseModel):
    provider: str = "sentence_transformers"
    model: str = "all-MiniLM-L6-v2"
    api_key_env: str = "GEMINI_API_KEY"
    base_url: str = "http://localhost:11434"
    output_dimensionality: Optional[int] = None  # Gemini: 768, 1536, or 3072; use 1536 for pgvector (ivfflat <= 2000)


class VectorStoreConfig(BaseModel):
    provider: str = "pgvector"
    collection: str = "old_mutual_chunks"
    path: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    url: Optional[str] = None  # Qdrant Cloud/remote URL, e.g. https://xxx.<region>.cloud.qdrant.io
    api_key: Optional[str] = None  # Qdrant Cloud API key


class HybridRetrievalConfig(BaseModel):
    enabled: bool = False
    dense_weight: float = 0.7
    sparse_weight: float = 0.3


class RetrievalConfig(BaseModel):
    top_k: int = 5
    hybrid: HybridRetrievalConfig = Field(default_factory=HybridRetrievalConfig)


class GenerationConfig(BaseModel):
    enabled: bool = True
    backend: str = "gemini"
    model: str = "gemini-3.6-flash"
    api_key_env: str = "GEMINI_API_KEY"


class RAGConfig(BaseModel):
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)


def load_rag_config(config_path: Optional[Path] = None) -> RAGConfig:
    """
    Load RAG config from YAML. Default path: config/rag_config.yml.

    Environment variables override the YAML so the same config works locally
    and in hosted deployments (e.g. Render/Neon) without editing the file:

      RAG_VECTOR_PROVIDER      -> vector_store.provider (pgvector | qdrant_local | qdrant_http)
      RAG_EMBEDDINGS_PROVIDER  -> embeddings.provider
      QDRANT_URL               -> vector_store.url   (Qdrant Cloud cluster URL)
      QDRANT_API_KEY           -> vector_store.api_key
      QDRANT_COLLECTION        -> vector_store.collection
      QDRANT_HOST              -> vector_store.host
      QDRANT_PORT              -> vector_store.port

    Switch the vector store at runtime purely via env: set RAG_VECTOR_PROVIDER=pgvector
    to use DATABASE_URL, or RAG_VECTOR_PROVIDER=qdrant_http to use QDRANT_URL + QDRANT_API_KEY.
    """
    if config_path is None:
        config_path = Path(__file__).resolve().parent.parent.parent / "config" / "rag_config.yml"
    if not config_path.exists():
        logger.warning("RAG config not found at %s, using defaults", config_path)
        cfg = RAGConfig()
    else:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        cfg = RAGConfig(**data)

    _apply_env_overrides(cfg)
    return cfg


def _apply_env_overrides(cfg: RAGConfig) -> None:
    """Apply environment variable overrides onto a loaded RAGConfig in place.

    Values are stripped so accidental surrounding whitespace (e.g. a trailing
    newline in QDRANT_API_KEY) never reaches the vector store client, where it
    would produce invalid HTTP headers.
    """
    provider = os.environ.get("RAG_VECTOR_PROVIDER")
    if provider:
        cfg.vector_store.provider = provider.strip()

    embeddings_provider = os.environ.get("RAG_EMBEDDINGS_PROVIDER")
    if embeddings_provider:
        cfg.embeddings.provider = embeddings_provider.strip()

    url = os.environ.get("QDRANT_URL")
    if url:
        cfg.vector_store.url = url.strip()

    api_key = os.environ.get("QDRANT_API_KEY")
    if api_key:
        cfg.vector_store.api_key = api_key.strip()

    collection = os.environ.get("QDRANT_COLLECTION")
    if collection:
        cfg.vector_store.collection = collection.strip()

    host = os.environ.get("QDRANT_HOST")
    if host:
        cfg.vector_store.host = host.strip()

    port = os.environ.get("QDRANT_PORT")
    if port:
        try:
            cfg.vector_store.port = int(port)
        except ValueError:
            logger.warning("QDRANT_PORT is not an integer: %r", port)
