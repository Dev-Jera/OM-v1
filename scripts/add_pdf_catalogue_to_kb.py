#!/usr/bin/env python3
"""
End-to-end script to add a product catalogue PDF into the KB.

Steps:
1. Process PDF into JSONL chunks
2. Append unique chunks into KB chunks JSONL
3. Upsert PDF chunks into configured vector store
4. Rebuild BM25 index (for hybrid retrieval)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.processors.pdf_catalogue_processor import PDFCatalogueProcessor
from src.rag.ingest import ingest_chunks_to_qdrant
from src.rag.keyword_search import BM25KeywordSearch
from src.utils.processing_config_loader import load_processing_config
from src.utils.rag_config_loader import load_rag_config


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def append_unique_chunks(source_chunks: Path, kb_chunks_file: Path) -> Tuple[int, int]:
    existing_ids: set[str] = set()
    if kb_chunks_file.exists():
        with open(kb_chunks_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                chunk_id = obj.get("id")
                if chunk_id:
                    existing_ids.add(str(chunk_id))

    kb_chunks_file.parent.mkdir(parents=True, exist_ok=True)

    appended = 0
    skipped = 0
    with open(source_chunks, "r", encoding="utf-8") as src, open(kb_chunks_file, "a", encoding="utf-8") as dest:
        for line in src:
            payload = line.strip()
            if not payload:
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                skipped += 1
                continue

            chunk_id = str(obj.get("id") or "")
            if not chunk_id or chunk_id in existing_ids:
                skipped += 1
                continue

            dest.write(json.dumps(obj, ensure_ascii=False) + "\n")
            existing_ids.add(chunk_id)
            appended += 1

    return appended, skipped


def _first_doc_id_from_documents_file(documents_file: Path) -> str | None:
    if not documents_file.exists():
        return None
    with open(documents_file, "r", encoding="utf-8") as f:
        for line in f:
            payload = line.strip()
            if not payload:
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            doc_id = obj.get("doc_id")
            if doc_id:
                return str(doc_id)
    return None


def _qdrant_doc_exists(rag_cfg: Any, doc_id: str) -> bool:
    provider = (rag_cfg.vector_store.provider or "").lower()
    if provider not in ("qdrant_http", "qdrant_local"):
        return False

    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qm

    collection = rag_cfg.vector_store.collection or "old_mutual_chunks"
    if provider == "qdrant_local":
        client = QdrantClient(path=rag_cfg.vector_store.path or "data/qdrant")
    else:
        client = QdrantClient(host=rag_cfg.vector_store.host or "localhost", port=rag_cfg.vector_store.port or 6333)

    try:
        points, _next = client.scroll(
            collection_name=collection,
            scroll_filter=qm.Filter(must=[qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id))]),
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        return bool(points)
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Process PDF catalogue and add it to KB/vector DB")
    parser.add_argument(
        "--pdf-path",
        type=Path,
        default=Path("data/raw/pdf/Insurance Product Catalogue (1).pdf"),
        help="Path to the source PDF",
    )
    parser.add_argument("--processing-config", type=Path, default=None, help="Path to processing config YAML")
    parser.add_argument("--rag-config", type=Path, default=None, help="Path to RAG config YAML")
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"), help="Output directory")
    parser.add_argument("--documents-file", type=str, default="pdf_catalogue_documents.jsonl", help="PDF documents JSONL filename")
    parser.add_argument("--pdf-chunks-file", type=str, default="pdf_catalogue_chunks.jsonl", help="PDF chunks JSONL filename")
    parser.add_argument(
        "--kb-chunks-file",
        type=Path,
        default=Path("data/processed/website_chunks.jsonl"),
        help="Main KB chunks JSONL used for hybrid index rebuild",
    )
    parser.add_argument("--doc-id", type=str, default=None, help="Optional fixed doc_id")
    parser.add_argument("--title", type=str, default=None, help="Optional fixed title")
    parser.add_argument("--source-url", type=str, default=None, help="Optional source URL metadata")
    parser.add_argument("--skip-append", action="store_true", help="Do not append PDF chunks into the KB chunks file")
    parser.add_argument("--skip-vector-upsert", action="store_true", help="Do not upsert into vector DB")
    parser.add_argument("--skip-bm25", action="store_true", help="Do not rebuild BM25 keyword index")
    parser.add_argument(
        "--skip-vector-if-doc-exists",
        action="store_true",
        help="For Qdrant providers, skip vector upsert when at least one point with this doc_id already exists",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    try:
        processing_cfg = load_processing_config(args.processing_config)
        processor = PDFCatalogueProcessor(
            chunk_size_words=processing_cfg.chunking.chunk_size,
            chunk_overlap_words=processing_cfg.chunking.chunk_overlap,
            min_chunk_chars=processing_cfg.validation.min_chunk_length,
            max_chunk_chars=processing_cfg.validation.max_chunk_length,
        )

        stats = processor.process(
            args.pdf_path,
            output_dir=args.output_dir,
            documents_filename=args.documents_file,
            chunks_filename=args.pdf_chunks_file,
            doc_id=args.doc_id,
            title=args.title,
            source_url=args.source_url,
        )
        logger.info("PDF processed: pages=%s chunks=%s", stats.pages_processed, stats.chunks_written)

        pdf_chunks_path = args.output_dir / args.pdf_chunks_file

        if not args.skip_append:
            appended, skipped = append_unique_chunks(pdf_chunks_path, args.kb_chunks_file)
            logger.info("KB chunks updated: appended=%s skipped=%s file=%s", appended, skipped, args.kb_chunks_file)

        if not args.skip_vector_upsert:
            rag_cfg = load_rag_config(args.rag_config)
            doc_id_for_check = args.doc_id or _first_doc_id_from_documents_file(args.output_dir / args.documents_file)
            should_skip_vector = False
            if args.skip_vector_if_doc_exists and doc_id_for_check:
                should_skip_vector = _qdrant_doc_exists(rag_cfg, doc_id_for_check)
                if should_skip_vector:
                    logger.info("Vector upsert skipped because doc_id already exists in vector store: %s", doc_id_for_check)

            if not should_skip_vector:
                total = ingest_chunks_to_qdrant(pdf_chunks_path, rag_cfg)
                logger.info(
                    "Vector upsert complete: chunks=%s provider=%s collection=%s",
                    total,
                    rag_cfg.vector_store.provider,
                    rag_cfg.vector_store.collection,
                )

        if not args.skip_bm25:
            index_source = args.kb_chunks_file if args.kb_chunks_file.exists() else pdf_chunks_path
            bm25 = BM25KeywordSearch()
            indexed = bm25.build_index(index_source)
            logger.info("BM25 index rebuilt from %s with %s chunks", index_source, indexed)

        logger.info("DONE")
        return 0
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130
    except Exception as e:
        logger.error("Failed to add PDF catalogue to KB: %s: %s", type(e).__name__, str(e), exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())