#!/usr/bin/env python3
"""
Add knowledge from a drop folder into the KB / vector store.

Drop files into a folder and run this script:
- PDF files (.pdf)      -> processed by PDFCatalogueProcessor
- Text files (.txt/.md) -> processed by TextFileProcessor

Steps per run:
1. Process every supported file into chunks (one batch)
2. Append unique chunks into the KB chunks JSONL (dedupe by chunk id)
3. Upsert chunks into the configured vector store (pgvector or Qdrant)
4. Rebuild the BM25 keyword index

Usage (from repo root):
  python scripts/add_knowledge_folder.py
  python scripts/add_knowledge_folder.py --input-dir data/raw/knowledge

Uses .env for QDRANT_URL / QDRANT_API_KEY / QDRANT_COLLECTION / GEMINI_API_KEY.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from src.rag.ingest import ingest_chunks_to_qdrant
from src.rag.keyword_search import BM25KeywordSearch
from src.processors.pdf_catalogue_processor import PDFCatalogueProcessor
from src.processors.text_processor import TextFileProcessor
from src.utils.processing_config_loader import load_processing_config
from src.utils.rag_config_loader import load_rag_config

from add_pdf_catalogue_to_kb import append_unique_chunks, _qdrant_doc_exists

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf": "pdf", ".txt": "text", ".md": "text"}


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def _discover_files(input_dir: Path) -> List[Path]:
    if not input_dir.exists():
        return []
    files = []
    for path in sorted(input_dir.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(path)
    return files


def _process_file(
    path: Path,
    index: int,
    processing_cfg: Any,
    output_dir: Path,
) -> List[dict[str, Any]]:
    kind = SUPPORTED_EXTENSIONS.get(path.suffix.lower())

    if kind == "pdf":
        processor = PDFCatalogueProcessor(
            chunk_size_words=processing_cfg.chunking.chunk_size,
            chunk_overlap_words=processing_cfg.chunking.chunk_overlap,
            min_chunk_chars=processing_cfg.validation.min_chunk_length,
            max_chunk_chars=processing_cfg.validation.max_chunk_length,
        )
        documents_filename = f"__knowledge_{index}_docs.jsonl"
        chunks_filename = f"__knowledge_{index}_chunks.jsonl"
        processor.process(
            path,
            output_dir=output_dir,
            documents_filename=documents_filename,
            chunks_filename=chunks_filename,
            title=path.stem.replace("_", " ").replace("-", " ").strip(),
        )
    else:
        processor = TextFileProcessor(
            chunk_size_words=processing_cfg.chunking.chunk_size,
            chunk_overlap_words=processing_cfg.chunking.chunk_overlap,
            min_chunk_chars=processing_cfg.validation.min_chunk_length,
            max_chunk_chars=processing_cfg.validation.max_chunk_length,
        )
        documents_filename = f"__knowledge_{index}_docs.jsonl"
        chunks_filename = f"__knowledge_{index}_chunks.jsonl"
        processor.process(
            path,
            output_dir=output_dir,
            documents_filename=documents_filename,
            chunks_filename=chunks_filename,
            title=path.stem.replace("_", " ").replace("-", " ").strip(),
        )

    chunks_path = output_dir / chunks_filename
    chunks: List[dict[str, Any]] = []
    with chunks_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                chunks.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    chunks_path.unlink(missing_ok=True)
    (output_dir / documents_filename).unlink(missing_ok=True)
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser(description="Add PDF/text knowledge from a drop folder into the KB")
    parser.add_argument("--input-dir", type=Path, default=Path("data/raw/knowledge"), help="Folder containing PDFs and .txt/.md files")
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"), help="Working output directory")
    parser.add_argument("--combined-chunks-file", type=str, default="knowledge_chunks.jsonl", help="Combined chunks JSONL filename (working file)")
    parser.add_argument(
        "--kb-chunks-file",
        type=Path,
        default=Path("data/processed/website_chunks.jsonl"),
        help="Main KB chunks JSONL used for hybrid index rebuild",
    )
    parser.add_argument("--processing-config", type=Path, default=None, help="Path to processing config YAML")
    parser.add_argument("--rag-config", type=Path, default=None, help="Path to RAG config YAML")
    parser.add_argument("--skip-append", action="store_true", help="Do not append chunks into the KB chunks file")
    parser.add_argument("--skip-vector-upsert", action="store_true", help="Do not upsert into vector DB")
    parser.add_argument("--skip-bm25", action="store_true", help="Do not rebuild BM25 keyword index")
    parser.add_argument(
        "--skip-vector-if-doc-exists",
        action="store_true",
        help="For vector providers, skip upsert when all doc_ids already exist in the vector store",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    setup_logging(args.verbose)

    args.input_dir.mkdir(parents=True, exist_ok=True)
    files = _discover_files(args.input_dir)
    if not files:
        logger.warning("No supported files found in %s. Drop .pdf/.txt/.md files there and re-run.", args.input_dir)
        return 0

    logger.info("Found %s file(s) in %s", len(files), args.input_dir)
    for path in files:
        logger.info("  - %s (%s)", path.name, path.suffix.lower().lstrip("."))

    processing_cfg = load_processing_config(args.processing_config)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    all_chunks: List[dict[str, Any]] = []
    failed: List[str] = []
    for index, path in enumerate(files):
        try:
            chunks = _process_file(path, index, processing_cfg, args.output_dir)
            logger.info("Processed %s -> %s chunk(s)", path.name, len(chunks))
            all_chunks.extend(chunks)
        except Exception as e:
            logger.error("Failed to process %s: %s", path.name, e)
            failed.append(path.name)

    if not all_chunks:
        logger.warning("No chunks produced. files_failed=%s", failed or "none")
        return 1 if failed else 0

    combined_path = args.output_dir / args.combined_chunks_file
    with combined_path.open("w", encoding="utf-8") as handle:
        for chunk in all_chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    logger.info("Combined chunks written: %s (%s)", combined_path, len(all_chunks))

    if not args.skip_append:
        appended, skipped = append_unique_chunks(combined_path, args.kb_chunks_file)
        logger.info("KB chunks updated: appended=%s skipped=%s file=%s", appended, skipped, args.kb_chunks_file)

    if not args.skip_vector_upsert:
        rag_cfg = load_rag_config(args.rag_config)
        doc_ids = sorted({str(chunk.get("doc_id") or "") for chunk in all_chunks if chunk.get("doc_id")})
        should_skip_vector = False
        if args.skip_vector_if_doc_exists and doc_ids:
            existing = [d for d in doc_ids if _qdrant_doc_exists(rag_cfg, d)]
            should_skip_vector = len(existing) == len(doc_ids)
            if should_skip_vector:
                logger.info("Vector upsert skipped because all doc_ids already exist: %s", existing)

        if not should_skip_vector:
            total = ingest_chunks_to_qdrant(combined_path, rag_cfg)
            logger.info(
                "Vector upsert complete: chunks=%s provider=%s collection=%s",
                total,
                rag_cfg.vector_store.provider,
                rag_cfg.vector_store.collection,
            )

    if not args.skip_bm25:
        index_source = args.kb_chunks_file if args.kb_chunks_file.exists() else combined_path
        bm25 = BM25KeywordSearch()
        indexed = bm25.build_index(index_source)
        logger.info("BM25 index rebuilt from %s with %s chunks", index_source, indexed)

    logger.info("DONE. files_processed=%s files_failed=%s chunks=%s", len(files) - len(failed), failed or "none", len(all_chunks))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())