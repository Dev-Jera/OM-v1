"""
Load and validate RAG configuration (embeddings, vector store, retrieval, generation).
Supports pgvector and Qdrant as vector store providers.
"""

from __future__ import annotations

import logging
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
    model: str = "gemini-1.5-flash"
    api_key_env: str = "GEMINI_API_KEY"


class RAGConfig(BaseModel):
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)


def load_rag_config(config_path: Optional[Path] = None) -> RAGConfig:
    """
    Load RAG config from YAML. Default path: config/rag_config.yml.
    """
    if config_path is None:
        config_path = Path(__file__).resolve().parent.parent.parent / "config" / "rag_config.yml"
    if not config_path.exists():
        logger.warning("RAG config not found at %s, using defaults", config_path)
        return RAGConfig()
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return RAGConfig(**data)
