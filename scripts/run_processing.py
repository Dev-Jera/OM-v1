#!/usr/bin/env python3
"""
Production script to process raw scraped website data into chunked JSONL.

Outputs:
- data/processed/website_documents.jsonl
- data/processed/website_chunks.jsonl
- data/processed/website_index.json (optional, per config)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

# Add repo root to path so `src.*` imports work when running from scripts/
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.processors.website_processor import WebsiteProcessor
from src.utils.processing_config_loader import load_processing_config


def setup_logging(verbose: bool = False, log_file: Optional[Path] = None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )


def find_latest_website_scrape(raw_dir: Path) -> Path:
    candidates = sorted(raw_dir.glob("website_scrape_*.json"), reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No website scrape files found in {raw_dir}")

    def _is_viable_scrape(path: Path) -> bool:
        # Very small files are typically blocked/empty scrape outputs.
        if path.stat().st_size < 2048:
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False

        if isinstance(data, list):
            return len(data) > 0
        if not isinstance(data, dict):
            return False

        products = data.get("products") or {}
        if isinstance(products, dict):
            for subcats in products.values():
                if isinstance(subcats, dict):
                    for items in subcats.values():
                        if isinstance(items, list) and items:
                            return True
        for key in ("articles", "faqs", "info_pages"):
            v = data.get(key)
            if isinstance(v, list) and v:
                return True
            if isinstance(v, dict) and any(isinstance(items, list) and items for items in v.values()):
                return True
        return False

    for candidate in candidates:
        if _is_viable_scrape(candidate):
            return candidate
    raise FileNotFoundError(
        f"No viable website scrape files found in {raw_dir}. "
        "Latest files may be empty/blocked (e.g., HTTP 403)."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Process raw scrape JSON into chunked JSONL for RAG")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to processing config YAML file (default: config/processing_config.yml)",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to raw scrape JSON (e.g. data/raw/website/website_scrape_*.json)",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Use the latest raw scrape file from data/raw/website/",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed"),
        help="Output directory (default: data/processed)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path("logs/processing.log"),
        help="Path to log file (default: logs/processing.log)",
    )

    args = parser.parse_args()
    setup_logging(verbose=args.verbose, log_file=args.log_file)
    logger = logging.getLogger(__name__)

    try:
        config = load_processing_config(args.config)
        processor = WebsiteProcessor(config)

        raw_dir = Path("data/raw/website")
        input_path: Optional[Path] = args.input
        if args.latest or input_path is None:
            input_path = find_latest_website_scrape(raw_dir)

        logger.info("Processing input: %s", input_path)
        logger.info("Output dir: %s", args.output_dir)

        stats = processor.process(input_path, output_dir=args.output_dir)

        logger.info("DONE")
        logger.info("Documents written: %s", stats.documents_written)
        logger.info("Chunks written: %s", stats.chunks_written)
        logger.info("Chunks invalid (skipped): %s", stats.chunks_invalid)
        logger.info("Chunks duplicates (skipped): %s", stats.chunks_duplicates_skipped)
        return 0
    except KeyboardInterrupt:
        logger.warning("Processing interrupted by user")
        return 130
    except Exception as e:
        logger.error("Error during processing: %s: %s", type(e).__name__, str(e), exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

