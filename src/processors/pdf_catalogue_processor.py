"""
PDF catalogue processor.

Extracts text from a product catalogue PDF and writes:
- documents JSONL (1 document per PDF)
- chunks JSONL (chunked per page)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

try:
    from PyPDF2 import PdfReader
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    raise RuntimeError("PyPDF2 is required for PDF ingestion. Install dependencies from requirements.txt.") from exc

try:
    import pdfplumber  # optional: much better text/table extraction
except ImportError:  # pragma: no cover - pdfplumber is optional
    pdfplumber = None

logger = logging.getLogger(__name__)


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    return text.strip("_") or "catalogue"


def _normalize_text(value: str) -> str:
    if not value:
        return ""
    value = value.replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _split_words(text: str, chunk_size_words: int, overlap_words: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    if chunk_size_words <= 0 or len(words) <= chunk_size_words:
        return [text]

    overlap_words = max(0, min(overlap_words, chunk_size_words - 1))
    step = max(1, chunk_size_words - overlap_words)
    chunks: list[str] = []

    for start in range(0, len(words), step):
        end = min(len(words), start + chunk_size_words)
        piece = " ".join(words[start:end]).strip()
        if piece:
            chunks.append(piece)
        if end >= len(words):
            break
    return chunks


def _split_chars(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    s = text.strip()
    if not s:
        return []
    if max_chars <= 0 or len(s) <= max_chars:
        return [s]

    overlap_chars = max(0, min(overlap_chars, max_chars - 1))
    step = max(1, max_chars - overlap_chars)
    out: list[str] = []
    for start in range(0, len(s), step):
        end = min(len(s), start + max_chars)
        piece = s[start:end].strip()
        if piece:
            out.append(piece)
        if end >= len(s):
            break
    return out


def _date_from_filename(stem: str) -> str | None:
    """Extract a leading date (YYYY, YYYY-MM, or YYYY-MM-DD) from a filename stem."""
    match = re.match(r"^\s*(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", stem)
    if not match:
        return None
    year = match.group(1)
    month = match.group(2)
    day = match.group(3)
    if month and day:
        return f"{year}-{month}-{day}"
    if month:
        return f"{year}-{month}"
    return year


def _resolve_as_of(filename_stem: str, explicit: str | None = None) -> str:
    """Determine the 'as of' date for a chunk.

    Priority: explicit value, then a date embedded in the filename, then the current year.
    """
    if explicit:
        return explicit
    from_filename = _date_from_filename(filename_stem)
    if from_filename:
        return from_filename
    return str(date.today().year)


@dataclass(frozen=True)
class PDFProcessedStats:
    documents_written: int
    chunks_written: int
    chunks_invalid: int
    pages_processed: int


class PDFCatalogueProcessor:
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
        pdf_path: Path,
        *,
        output_dir: Path,
        documents_filename: str = "pdf_catalogue_documents.jsonl",
        chunks_filename: str = "pdf_catalogue_chunks.jsonl",
        doc_id: str | None = None,
        title: str | None = None,
        source_url: str | None = None,
        as_of: str | None = None,
    ) -> PDFProcessedStats:
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        page_texts = list(self._iter_pdf_pages(pdf_path))
        if not page_texts:
            raise ValueError(f"No readable text found in PDF: {pdf_path}")

        resolved_title = title or pdf_path.stem
        resolved_doc_id = doc_id or f"pdf:product_catalogue:{_slugify(pdf_path.stem)}"
        resolved_as_of = _resolve_as_of(pdf_path.stem, explicit=as_of)

        output_dir.mkdir(parents=True, exist_ok=True)
        docs_path = output_dir / documents_filename
        chunks_path = output_dir / chunks_filename

        document = {
            "doc_id": resolved_doc_id,
            "type": "pdf_catalogue",
            "title": resolved_title,
            "url": source_url or f"file:{pdf_path.as_posix()}",
            "category": "catalogue",
            "subcategory": "product_catalogue",
            "source_file": str(pdf_path),
            "as_of": resolved_as_of,
            "page_count": len(page_texts),
            "sections": [{"heading": f"Page {page_num}", "content": text} for page_num, text in page_texts],
            "faqs": [],
        }

        chunks_written = 0
        chunks_invalid = 0

        with open(docs_path, "w", encoding="utf-8") as f_docs, open(chunks_path, "w", encoding="utf-8") as f_chunks:
            f_docs.write(json.dumps(document, ensure_ascii=False) + "\n")

            for chunk in self._iter_chunks(document, page_texts):
                if len(chunk["text"]) < self.min_chunk_chars:
                    chunks_invalid += 1
                    continue
                chunks_written += 1
                f_chunks.write(json.dumps(chunk, ensure_ascii=False) + "\n")

        logger.info(
            "Processed PDF catalogue. pages=%s chunks=%s invalid=%s output=%s",
            len(page_texts),
            chunks_written,
            chunks_invalid,
            output_dir,
        )

        return PDFProcessedStats(
            documents_written=1,
            chunks_written=chunks_written,
            chunks_invalid=chunks_invalid,
            pages_processed=len(page_texts),
        )

    def _iter_pdf_pages(self, pdf_path: Path) -> Iterable[tuple[int, str]]:
        if pdfplumber is not None:
            try:
                with pdfplumber.open(str(pdf_path)) as pdf:
                    for i, page in enumerate(pdf.pages, start=1):
                        text = _normalize_text(page.extract_text() or "")
                        # Append table rows so tabular data (e.g. bank account
                        # tables) is preserved as structured, searchable text
                        # instead of being lost to layout flattening.
                        try:
                            tables = page.extract_tables()
                        except Exception:  # pragma: no cover - defensive
                            tables = []
                        if tables:
                            table_lines = []
                            for table in tables:
                                for row in table:
                                    cells = [(c or "").replace("\n", " ").strip() for c in row]
                                    cells = [c for c in cells if c]
                                    if cells:
                                        table_lines.append(" | ".join(cells))
                            table_text = "\n".join(table_lines)
                            if table_text:
                                text = f"{text}\n{table_text}".strip() if text else table_text
                        if text:
                            yield i, text
                return
            except Exception as exc:  # pragma: no cover - fall back to PyPDF2
                logger.warning("pdfplumber extraction failed, falling back to PyPDF2: %s", exc)

        reader = PdfReader(str(pdf_path))
        for i, page in enumerate(reader.pages, start=1):
            text = _normalize_text(page.extract_text() or "")
            if text:
                yield i, text

    def _iter_chunks(self, document: dict, page_texts: list[tuple[int, str]]) -> Iterable[dict]:
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

        for page_number, page_text in page_texts:
            for j, piece in enumerate(
                _split_words(
                    page_text,
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
                    chunk_id = f"{document['doc_id']}:page:{page_number}:chunk:{j}.{k}"
                    yield {
                        "id": chunk_id,
                        "chunk_type": "catalogue_page",
                        "text": capped,
                        "section_kind": "content",
                        "section_heading": f"Page {page_number}",
                        "section_index": page_number - 1,
                        "page_number": page_number,
                        **base_meta,
                    }
