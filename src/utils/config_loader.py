"""
Configuration loader for RAG system
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, ValidationError
import logging

logger = logging.getLogger(__name__)


class RateLimitConfig(BaseModel):
    """Rate limiting configuration"""

    enabled: bool = True
    requests_per_minute: int = Field(default=30, ge=1, le=1000)


class GeneralConfig(BaseModel):
    """General scraping configuration"""

    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " "AppleWebKit/537.36 (KHTML, like Gecko) " "Chrome/120.0.0.0 Safari/537.36"
    rate_limit: RateLimitConfig = Field(default_factory=lambda: RateLimitConfig())


class WebsiteScraperConfig(BaseModel):
    """Website scraper configuration"""

    base_url: str
    output_dir: str = "data/raw/website"
    delay: float = Field(ge=0.0, default=2.0)
    max_retries: int = Field(ge=1, le=10, default=3)
    priority_urls: list[str] = Field(default_factory=list)
    article_urls: list[str] = Field(default_factory=list)
    info_page_urls: dict[str, list[str]] = Field(default_factory=dict)


class PDFScraperConfig(BaseModel):
    """PDF scraper configuration"""

    input_dir: str = "data/raw/pdfs"
    output_dir: str = "data/raw/pdf_content"
    extract_tables: bool = True


class ScrapingConfig(BaseModel):
    """Complete scraping configuration"""

    scrapers: Dict[str, Any]
    general: GeneralConfig


def load_scraping_config(config_path: Optional[Path] = None) -> ScrapingConfig:
    """
    Load and validate scraping configuration from YAML file

    Args:
        config_path: Path to config file. Defaults to config/scraping_config.yml

    Returns:
        Validated ScrapingConfig object

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValidationError: If config doesn't match schema
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config" / "scraping_config.yml"

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    try:
        # Validate and create config object
        config = ScrapingConfig(**config_data)
        logger.info(f"Successfully loaded config from {config_path}")
        return config
    except ValidationError as e:
        logger.error(f"Config validation failed: {e}")
        raise


def get_website_config(config: ScrapingConfig) -> WebsiteScraperConfig:
    """Extract and validate website scraper config"""
    if "website" not in config.scrapers:
        raise ValueError("Website scraper config not found")

    website_data = config.scrapers["website"]
    return WebsiteScraperConfig(**website_data)


def get_pdf_config(config: ScrapingConfig) -> PDFScraperConfig:
    """Extract and validate PDF scraper config"""
    if "pdf" not in config.scrapers:
        raise ValueError("PDF scraper config not found")

    pdf_data = config.scrapers["pdf"]
    return PDFScraperConfig(**pdf_data)
