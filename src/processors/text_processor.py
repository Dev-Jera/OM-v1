"""
Text knowledge processor.

Reads a plain-text or Markdown file and writes:
- documents JSONL (1 document per file)
- chunks JSONL (chunked with the same word/char settings as the PDF processor)

Supports dropping pasted information (.txt / .md) into the knowledge folder
without going through the website scraping pipeline.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.processors.pdf_catalogue_processor import (
    _normalize_text,
    _resolve_as_of,
    _slugify,
    _split_chars,
    _split_words,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextProcessedStats:
    documents_written: int
    chunks_written: int
    chunks_invalid: int
    text_length_chars: int


class TextFileProcessor:
    def __init__(
        self,
        *,
        chunk_size_words: int = 768,
        chunk_overlap_words: int = 100,
        min_chunk_chars: int = 50,
        max_chunk_chars: int = 2000,
    ):
        self.chunk_size_words = chunk_size_words
        self.chunk_overlap_words = chunk_overlap_words
        self.min_chunk_chars = min_chunk_chars
        self.max_chunk_chars = max_chunk_chars

    def process(
        self,
        text_path: Path,
        *,
        output_dir: Path,
        documents_filename: str = "text_knowledge_documents.jsonl",
        chunks_filename: str = "text_knowledge_chunks.jsonl",
        doc_id: str | None = None,
        title: str | None = None,
        source_url: str | None = None,
        as_of: str | None = None,
    ) -> TextProcessedStats:
        if not text_path.exists():
            raise FileNotFoundError(f"Text file not found: {text_path}")

        raw_text = text_path.read_text(encoding="utf-8", errors="replace")
        normalized = _normalize_text(raw_text)
        if not normalized:
            raise ValueError(f"No readable text found in file: {text_path}")

        resolved_title = title or text_path.stem.replace("_", " ").replace("-", " ").strip()
        resolved_doc_id = doc_id or f"text:knowledge:{_slugify(text_path.stem)}"
        resolved_as_of = _resolve_as_of(text_path.stem, explicit=as_of)

        output_dir.mkdir(parents=True, exist_ok=True)
        docs_path = output_dir / documents_filename
        chunks_path = output_dir / chunks_filename

        document = {
            "doc_id": resolved_doc_id,
            "type": "text_knowledge",
            "title": resolved_title,
            "url": source_url or f"file:{text_path.as_posix()}",
            "category": "knowledge",
            "subcategory": "custom",
            "source_file": str(text_path),
            "as_of": resolved_as_of,
            "sections": [{"heading": "Document", "content": normalized}],
            "faqs": [],
        }

        chunks_written = 0
        chunks_invalid = 0

        with open(docs_path, "w", encoding="utf-8") as f_docs, open(chunks_path, "w", encoding="utf-8") as f_chunks:
            f_docs.write(json.dumps(document, ensure_ascii=False) + "\n")

            for chunk in self._iter_chunks(document, normalized):
                if len(chunk["text"]) < self.min_chunk_chars:
                    chunks_invalid += 1
                    continue
                chunks_written += 1
                f_chunks.write(json.dumps(chunk, ensure_ascii=False) + "\n")

        logger.info(
            "Processed text file. chars=%s chunks=%s invalid=%s output=%s",
            len(normalized),
            chunks_written,
            chunks_invalid,
            output_dir,
        )

        return TextProcessedStats(
            documents_written=1,
            chunks_written=chunks_written,
            chunks_invalid=chunks_invalid,
            text_length_chars=len(normalized),
        )

    def _iter_chunks(self, document: dict, text: str) -> Iterable[dict]:
        base_meta = {
            "doc_id": document["doc_id"],
            "type": document["type"],
            "url": document["url"],
            "title": document["title"],
            "category": document["category"],
            "subcategory": document["subcategory"],
            "source_file": document["source_file"],
            "as_of": document["as_of"],
        }

        for j, piece in enumerate(
            _split_words(
                text,
                chunk_size_words=self.chunk_size_words,
                overlap_words=self.chunk_overlap_words,
            )
        ):
            for k, capped in enumerate(
                _split_chars(
                    piece,
                    max_chars=self.max_chunk_chars,
                    overlap_chars=min(200, max(1, self.max_chunk_chars // 10)),
                )
            ):
                chunk_id = f"{document['doc_id']}:chunk:{j}.{k}"
                yield {
                    "id": chunk_id,
                    "chunk_type": "knowledge",
                    "text": capped,
                    "section_kind": "content",
                    "section_heading": "Document",
                    "section_index": 0,
                    **base_meta,
                }