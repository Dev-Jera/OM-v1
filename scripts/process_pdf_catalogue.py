#!/usr/bin/env python3
"""
Process a product catalogue PDF into KB-compatible JSONL files.

Outputs by default:
- data/processed/pdf_catalogue_documents.jsonl
- data/processed/pdf_catalogue_chunks.jsonl
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.processors.pdf_catalogue_processor import PDFCatalogueProcessor
from src.utils.processing_config_loader import load_processing_config


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Process product catalogue PDF into chunked JSONL for RAG")
    parser.add_argument(
        "--pdf-path",
        type=Path,
        default=Path("data/raw/pdf/Insurance Product Catalogue (1).pdf"),
        help="Path to the source PDF",
    )
    parser.add_argument(
        "--processing-config",
        type=Path,
        default=None,
        help="Path to processing config YAML (default: config/processing_config.yml)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed"),
        help="Output directory for JSONL files",
    )
    parser.add_argument(
        "--documents-file",
        type=str,
        default="pdf_catalogue_documents.jsonl",
        help="Output documents JSONL filename",
    )
    parser.add_argument(
        "--chunks-file",
        type=str,
        default="pdf_catalogue_chunks.jsonl",
        help="Output chunks JSONL filename",
    )
    parser.add_argument("--doc-id", type=str, default=None, help="Optional fixed doc_id")
    parser.add_argument("--title", type=str, default=None, help="Optional fixed document title")
    parser.add_argument("--source-url", type=str, default=None, help="Optional source URL metadata")
    parser.add_argument("--chunk-size", type=int, default=None, help="Override chunk size in words")
    parser.add_argument("--chunk-overlap", type=int, default=None, help="Override chunk overlap in words")
    parser.add_argument("--min-chars", type=int, default=None, help="Override min chunk length in characters")
    parser.add_argument("--max-chars", type=int, default=None, help="Override max chunk length in characters")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    try:
        cfg = load_processing_config(args.processing_config)
        processor = PDFCatalogueProcessor(
            chunk_size_words=args.chunk_size or cfg.chunking.chunk_size,
            chunk_overlap_words=args.chunk_overlap or cfg.chunking.chunk_overlap,
            min_chunk_chars=args.min_chars or cfg.validation.min_chunk_length,
            max_chunk_chars=args.max_chars or cfg.validation.max_chunk_length,
        )
        stats = processor.process(
            args.pdf_path,
            output_dir=args.output_dir,
            documents_filename=args.documents_file,
            chunks_filename=args.chunks_file,
            doc_id=args.doc_id,
            title=args.title,
            source_url=args.source_url,
        )

        logger.info("DONE")
        logger.info("Documents written: %s", stats.documents_written)
        logger.info("Pages processed: %s", stats.pages_processed)
        logger.info("Chunks written: %s", stats.chunks_written)
        logger.info("Chunks invalid (skipped): %s", stats.chunks_invalid)
        logger.info("Documents file: %s", args.output_dir / args.documents_file)
        logger.info("Chunks file: %s", args.output_dir / args.chunks_file)
        return 0
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130
    except Exception as e:
        logger.error("Error processing PDF catalogue: %s: %s", type(e).__name__, str(e), exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())