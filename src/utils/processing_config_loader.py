"""
Processing configuration loader for RAG system.

This module loads config/processing_config.yml and validates it with Pydantic.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


class CleaningConfig(BaseModel):
    normalize_unicode: bool = True
    fix_ocr_errors: bool = True
    normalize_terminology: bool = True


class ChunkingConfig(BaseModel):
    chunk_size: int = Field(default=768, ge=1)
    chunk_overlap: int = Field(default=100, ge=0)
    strategy: str = Field(default="semantic")


class MetadataExtractionConfig(BaseModel):
    enabled: bool = True
    extract_products: bool = True
    extract_insurance_types: bool = True


class ValidationConfig(BaseModel):
    enabled: bool = True
    min_chunk_length: int = Field(default=50, ge=0)
    max_chunk_length: int = Field(default=2000, ge=1)


class OutputConfig(BaseModel):
    format: str = Field(default="jsonl")
    create_index: bool = True


class ProcessingConfig(BaseModel):
    cleaning: CleaningConfig = Field(default_factory=CleaningConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    metadata_extraction: MetadataExtractionConfig = Field(default_factory=MetadataExtractionConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


def load_processing_config(config_path: Optional[Path] = None) -> ProcessingConfig:
    """
    Load and validate processing configuration from YAML file.

    Args:
        config_path: Path to config file. Defaults to config/processing_config.yml

    Returns:
        Validated ProcessingConfig object
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config" / "processing_config.yml"

    if not config_path.exists():
        raise FileNotFoundError(f"Processing config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f) or {}

    try:
        config = ProcessingConfig(**config_data)
        logger.info(f"Successfully loaded processing config from {config_path}")
        return config
    except ValidationError as e:
        logger.error(f"Processing config validation failed: {e}")
        raise
