"""
Website data processing pipeline.

Reads the raw scrape JSON produced by OldMutualWebsiteScraper and writes:
- documents.jsonl (one per page/product/article)
- chunks.jsonl (one per chunk, derived from content sections + FAQs)
- index.json (optional; maps doc_id -> chunk_ids + metadata)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from src.utils.content_validator import ContentValidator
from src.utils.processing_config_loader import ProcessingConfig
from src.processors.oldmutual_cleaner import OldMutualCleaner

logger = logging.getLogger(__name__)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _split_words(text: str, chunk_size_words: int, overlap_words: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    if chunk_size_words <= 0:
        return [text]
    if len(words) <= chunk_size_words:
        return [text]

    overlap_words = max(0, min(overlap_words, chunk_size_words - 1))
    step = max(1, chunk_size_words - overlap_words)
    chunks: list[str] = []

    for start in range(0, len(words), step):
        end = min(len(words), start + chunk_size_words)
        chunk = " ".join(words[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(words):
            break
    return chunks


def _split_chars(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    if max_chars <= 0:
        return [text]
    s = text.strip()
    if len(s) <= max_chars:
        return [s]

    overlap_chars = max(0, min(overlap_chars, max_chars - 1))
    step = max(1, max_chars - overlap_chars)
    out: list[str] = []
    for start in range(0, len(s), step):
        end = min(len(s), start + max_chars)
        part = s[start:end].strip()
        if part:
            out.append(part)
        if end >= len(s):
            break
    return out


def _detect_insurance_types(text: str) -> list[str]:
    t = text.lower()
    mapping = {
        "motor": ["motor", "vehicle", "car", "third party"],
        "travel": ["travel", "trip", "repatriation", "baggage"],
        "medical": ["medical", "hospital", "health", "clinic"],
        "life": ["life cover", "death benefit", "beneficiary"],
        "accident": ["accident", "disablement", "injury"],
        "liability": ["liability", "professional liability"],
        "investment": ["unit trust", "investment", "securities", "wealth management"],
    }
    found: list[str] = []
    for label, kws in mapping.items():
        if any(kw in t for kw in kws):
            found.append(label)
    return sorted(set(found))


def _classify_product_section(heading: str) -> str:
    h = heading.lower().strip()
    if "what's in it for you" in h or "what is in it for you" in h:
        return "benefits"
    if any(k in h for k in ["what is", "what’s", "what's"]):
        return "overview"
    if any(
        k in h
        for k in [
            "how do i apply",
            "how can i apply",
            "how to apply",
            "apply",
        ]
    ):
        return "application"
    if any(
        k in h
        for k in [
            "step ",
            "first time",
            "flexipay",
            "non flexipay",
            "banking options",
            "banking",
            "pay",
            "payments",
            "merchant code",
        ]
    ):
        return "payment_methods"
    return "general"


def _is_payment_section(heading: str, content: str) -> bool:
    h = heading.lower()
    c = content.lower()
    return any(
        k in h
        for k in [
            "step ",
            "first time",
            "flexipay",
            "non flexipay",
            "banking options",
            "banking",
            "payments",
        ]
    ) or any(k in c for k in ["dial *185#", "dial *291#", "merchant code", "pay merchant"])


@dataclass(frozen=True)
class ProcessedStats:
    documents_written: int
    chunks_written: int
    chunks_invalid: int
    chunks_duplicates_skipped: int


class WebsiteProcessor:
    def __init__(self, config: ProcessingConfig):
        self.config = config
        self.validator = ContentValidator(
            min_chunk_length=config.validation.min_chunk_length,
            max_chunk_length=config.validation.max_chunk_length,
            min_content_length=0,
            max_content_length=10_000_000,
            check_language=False,
        )
        self._seen_hashes: set[str] = set()
        self.cleaner = OldMutualCleaner(
            normalize_unicode=config.cleaning.normalize_unicode,
            fix_ocr_errors=config.cleaning.fix_ocr_errors,
            normalize_terminology=config.cleaning.normalize_terminology,
            improve_step_headings=True,
        )

    def process(
        self,
        input_json_path: Path,
        *,
        output_dir: Path,
        documents_filename: str = "website_documents.jsonl",
        chunks_filename: str = "website_chunks.jsonl",
        index_filename: str = "website_index.json",
    ) -> ProcessedStats:
        raw = self._load_raw(input_json_path)

        output_dir.mkdir(parents=True, exist_ok=True)
        documents_path = output_dir / documents_filename
        chunks_path = output_dir / chunks_filename
        index_path = output_dir / index_filename

        docs_written = 0
        chunks_written = 0
        chunks_invalid = 0
        chunks_dupes = 0

        index: dict[str, Any] = {}

        with open(documents_path, "w", encoding="utf-8") as f_docs, open(chunks_path, "w", encoding="utf-8") as f_chunks:
            for doc in self._iter_documents(raw):
                docs_written += 1
                f_docs.write(json.dumps(doc, ensure_ascii=False) + "\n")

                doc_id = doc["doc_id"]
                index_entry = {
                    "doc_id": doc_id,
                    "type": doc.get("type"),
                    "url": doc.get("url"),
                    "title": doc.get("title"),
                    "category": doc.get("category"),
                    "subcategory": doc.get("subcategory"),
                    "chunk_ids": [],
                }

                for chunk in self._iter_chunks(doc):
                    is_dup, _hash = self.validator.is_duplicate_content(chunk["text"], self._seen_hashes)
                    if is_dup:
                        chunks_dupes += 1
                        continue

                    valid_result = self.validator.validate_chunk(chunk["text"])
                    if self.config.validation.enabled and not valid_result["valid"]:
                        chunks_invalid += 1
                        continue

                    chunks_written += 1
                    index_entry["chunk_ids"].append(chunk["id"])
                    f_chunks.write(json.dumps(chunk, ensure_ascii=False) + "\n")

                index[doc_id] = index_entry

        if self.config.output.create_index:
            with open(index_path, "w", encoding="utf-8") as f_index:
                json.dump(index, f_index, ensure_ascii=False, indent=2)

        logger.info(
            "Processing complete. docs=%s chunks=%s invalid=%s dupes=%s out=%s",
            docs_written,
            chunks_written,
            chunks_invalid,
            chunks_dupes,
            str(output_dir),
        )

        return ProcessedStats(
            documents_written=docs_written,
            chunks_written=chunks_written,
            chunks_invalid=chunks_invalid,
            chunks_duplicates_skipped=chunks_dupes,
        )

    def _load_raw(self, path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _iter_documents(self, raw: dict) -> Iterable[dict]:
        products = raw.get("products") or {}
        if isinstance(products, dict):
            for category, subcats in products.items():
                if not isinstance(subcats, dict):
                    continue
                for subcat, items in subcats.items():
                    if not isinstance(items, list):
                        continue
                    for item in items:
                        doc = self._build_doc(item, fallback_title=_safe_text(item.get("display_name") or item.get("product_name")))
                        doc["category"] = _safe_text(category) or doc.get("category")
                        doc["subcategory"] = _safe_text(subcat) or doc.get("subcategory")
                        doc["doc_id"] = f"website:product:{category}/{subcat}/{doc.get('product_id', 'unknown')}"
                        yield doc

        articles = raw.get("articles") or {}
        if isinstance(articles, dict):
            for category, items in articles.items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    doc = self._build_doc(item, fallback_title=_safe_text(item.get("title") or item.get("article_id")))
                    doc["category"] = _safe_text(category) or doc.get("category")
                    doc["doc_id"] = f"website:article:{category}/{doc.get('article_id', 'unknown')}"
                    yield doc
        elif isinstance(articles, list):
            for item in articles:
                doc = self._build_doc(item, fallback_title=_safe_text(item.get("title") or item.get("article_id")))
                cat = _safe_text(doc.get("category") or "general")
                doc["doc_id"] = f"website:article:{cat}/{doc.get('article_id', 'unknown')}"
                yield doc

        info_pages = raw.get("info_pages") or {}
        if isinstance(info_pages, dict):
            for group, items in info_pages.items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    doc = self._build_doc(item, fallback_title=_safe_text(item.get("title") or item.get("page_id")))
                    doc["group"] = _safe_text(group)
                    page_id = _safe_text(item.get("page_id") or item.get("info_id") or item.get("title") or "unknown")
                    doc["doc_id"] = f"website:info:{group}/{page_id}"
                    yield doc
        elif isinstance(info_pages, list):
            for item in info_pages:
                doc = self._build_doc(item, fallback_title=_safe_text(item.get("title") or item.get("page_id")))
                page_id = _safe_text(item.get("page_id") or item.get("info_id") or item.get("title") or "unknown")
                doc["doc_id"] = f"website:info:general/{page_id}"
                yield doc

        faq_pages = raw.get("faqs") or []
        if isinstance(faq_pages, list):
            for item in faq_pages:
                doc = self._build_doc(item, fallback_title=_safe_text(item.get("title") or item.get("faq_id") or "faq"))
                faq_id = _safe_text(item.get("faq_id") or item.get("title") or "unknown")
                doc["doc_id"] = f"website:faq_page:{faq_id}"
                yield doc

    def _build_doc(self, item: dict, *, fallback_title: str) -> dict:
        item_type = _safe_text(item.get("type") or "unknown")
        url = _safe_text(item.get("url"))
        title = _safe_text(item.get("display_name") or item.get("product_name") or item.get("title") or fallback_title)

        cleaned_sections = self.cleaner.clean_sections(item.get("content"))
        cleaned_faqs = self.cleaner.clean_faqs(item.get("faqs"))

        doc: dict[str, Any] = {
            "doc_id": "website:unknown",
            "type": item_type,
            "url": url,
            "title": title,
            "category": _safe_text(item.get("category")),
            "subcategory": _safe_text(item.get("subcategory")),
            "product_id": _safe_text(item.get("product_id")),
            "article_id": _safe_text(item.get("article_id")),
            "page_id": _safe_text(item.get("page_id")),
            "scraped_at": _safe_text(item.get("scraped_at")),
            "sections": cleaned_sections,
            "faqs": cleaned_faqs,
        }

        if self.config.metadata_extraction.enabled:
            combined = f"{title}\n" + "\n".join(
                [f"{s['heading']}\n{s['content']}" for s in cleaned_sections] + [f"{f['question']}\n{f['answer']}" for f in cleaned_faqs]
            )
            if self.config.metadata_extraction.extract_insurance_types:
                doc["insurance_types"] = _detect_insurance_types(combined)
            if self.config.metadata_extraction.extract_products and item_type == "product":
                doc["product_name"] = _safe_text(item.get("product_name") or title)

        return doc

    def _iter_chunks(self, doc: dict) -> Iterable[dict]:
        chunk_size = self.config.chunking.chunk_size
        chunk_overlap = self.config.chunking.chunk_overlap
        max_chars = self.config.validation.max_chunk_length

        base_meta = {
            "doc_id": doc.get("doc_id"),
            "type": doc.get("type"),
            "url": doc.get("url"),
            "title": doc.get("title"),
            "category": doc.get("category"),
            "subcategory": doc.get("subcategory"),
            "product_id": doc.get("product_id"),
            "article_id": doc.get("article_id"),
            "page_id": doc.get("page_id"),
            "scraped_at": doc.get("scraped_at"),
        }

        sections: list[dict[str, str]] = doc.get("sections") or []
        used_section_indexes: set[int] = set()

        doc_type = _safe_text(doc.get("type"))

        if doc_type == "product" and sections:
            payment_indexes: list[int] = []
            payment_parts: list[str] = []
            for idx, s in enumerate(sections):
                h = _safe_text(s.get("heading"))
                c = _safe_text(s.get("content"))
                if not (h or c):
                    continue
                if _is_payment_section(h, c):
                    payment_indexes.append(idx)
                    payment_parts.append("\n".join([p for p in [h, c] if p]).strip())

            if payment_parts:
                used_section_indexes.update(payment_indexes)
                combined = "\n\n".join([p for p in payment_parts if p]).strip()
                for j, part in enumerate(_split_words(combined, chunk_size_words=chunk_size, overlap_words=chunk_overlap)):
                    for k, capped in enumerate(_split_chars(part, max_chars=max_chars, overlap_chars=min(200, max_chars // 10))):
                        chunk_id = f"{doc['doc_id']}:payment_methods:chunk:{j}.{k}"
                        yield {
                            "id": chunk_id,
                            "chunk_type": "payment_methods",
                            "text": capped,
                            "section_kind": "content",
                            "section_heading": "Payment methods",
                            "section_index": -1,
                            **base_meta,
                        }

            overview_idx: Optional[int] = None
            benefits_idx: Optional[int] = None
            for idx, s in enumerate(sections):
                h = _safe_text(s.get("heading"))
                if not h:
                    continue
                t = _classify_product_section(h)
                if t == "overview" and overview_idx is None:
                    overview_idx = idx
                if t == "benefits" and benefits_idx is None:
                    benefits_idx = idx

            for label, idx in [("overview", overview_idx), ("benefits", benefits_idx)]:
                if idx is None:
                    continue
                if idx in used_section_indexes:
                    continue
                used_section_indexes.add(idx)
                h = _safe_text(sections[idx].get("heading"))
                c = _safe_text(sections[idx].get("content"))
                section_text = "\n".join([p for p in [h, c] if p]).strip()
                for j, part in enumerate(_split_words(section_text, chunk_size_words=chunk_size, overlap_words=chunk_overlap)):
                    for k, capped in enumerate(_split_chars(part, max_chars=max_chars, overlap_chars=min(200, max_chars // 10))):
                        chunk_id = f"{doc['doc_id']}:{label}:chunk:{j}.{k}"
                        yield {
                            "id": chunk_id,
                            "chunk_type": label,
                            "text": capped,
                            "section_kind": "content",
                            "section_heading": h,
                            "section_index": idx,
                            **base_meta,
                        }

        for i, section in enumerate(sections):
            if i in used_section_indexes:
                continue
            heading = _safe_text(section.get("heading"))
            content = _safe_text(section.get("content"))
            if not (heading or content):
                continue

            if doc_type == "product":
                chunk_type = _classify_product_section(heading)
            elif doc_type == "article":
                chunk_type = "article_section"
            elif doc_type == "info_page":
                chunk_type = "info_section"
            else:
                chunk_type = "general"

            section_text = "\n".join([p for p in [heading, content] if p]).strip()
            for j, part in enumerate(_split_words(section_text, chunk_size_words=chunk_size, overlap_words=chunk_overlap)):
                for k, capped in enumerate(_split_chars(part, max_chars=max_chars, overlap_chars=min(200, max_chars // 10))):
                    chunk_id = f"{doc['doc_id']}:section:{i}:chunk:{j}.{k}"
                    yield {
                        "id": chunk_id,
                        "chunk_type": chunk_type,
                        "text": capped,
                        "section_kind": "content",
                        "section_heading": heading,
                        "section_index": i,
                        **base_meta,
                    }

        faqs: list[dict[str, str]] = doc.get("faqs") or []
        for i, faq in enumerate(faqs):
            q = _safe_text(faq.get("question"))
            a = _safe_text(faq.get("answer"))
            if not (q or a):
                continue
            faq_text = "\n".join([p for p in [f"Q: {q}" if q else "", f"A: {a}" if a else ""] if p]).strip()
            for j, part in enumerate(_split_words(faq_text, chunk_size_words=chunk_size, overlap_words=chunk_overlap)):
                for k, capped in enumerate(_split_chars(part, max_chars=max_chars, overlap_chars=min(200, max_chars // 10))):
                    chunk_id = f"{doc['doc_id']}:faq:{i}:chunk:{j}.{k}"
                    yield {
                        "id": chunk_id,
                        "chunk_type": "faq",
                        "text": capped,
                        "section_kind": "faq",
                        "section_heading": q,
                        "section_index": i,
                        **base_meta,
                    }
