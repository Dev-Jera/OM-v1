"""Convert Zoho CRM product records into RAG chunks.

Chunks follow the same schema as website product chunks so the existing
ingester (scripts/generate_embeddings.py) and vector store treat them
identically. Every chunk uses a ``zoho:`` doc_id prefix, which
scripts/run_processing.py preserves across website re-scrapes.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ZOHO_PREFIX = "zoho:"


def slugify(value: str) -> str:
    """'Somesa Education Plan' -> 'somesa-education-plan'."""
    s = (value or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


class ZohoCRMProcessor:
    """Turn raw Zoho CRM record dicts into chunk-schema dicts + index entries."""

    def __init__(
        self,
        fields_config: Optional[Dict[str, Any]] = None,
        existing_index: Optional[Dict[str, Any]] = None,
    ) -> None:
        fields_config = fields_config or {}
        self.fields = fields_config.get("fields") or {}
        self.filter_cfg = fields_config.get("filter") or {}
        self.active_only = bool(self.filter_cfg.get("active_only", True))
        self.include_price = bool(fields_config.get("include_price_in_text", True))
        self.include_code = bool(fields_config.get("include_product_code_in_text", False))
        self.fallback_category = str(fields_config.get("slug_fallback_category") or "general")
        self.fallback_subcategory = str(fields_config.get("slug_fallback_subcategory") or "products")
        self.existing_index = existing_index or {}
        self._slug_doc_ids = self._build_existing_slug_map()

    def _build_existing_slug_map(self) -> Dict[str, str]:
        """Map product slug/title -> existing website doc_id for attachment."""
        mapping: Dict[str, str] = {}
        for doc_id, entry in self.existing_index.items():
            if entry.get("type") != "product":
                continue
            product_key = (entry.get("product_key") or "").strip() or doc_id
            slug = product_key.strip("/").split("/")[-1]
            if slug:
                mapping[slug] = doc_id
            title = (entry.get("title") or "").strip()
            if title:
                mapping[slugify(title)] = doc_id
        return mapping

    def _is_active(self, record: Dict[str, Any]) -> bool:
        field = self.fields.get("active")
        if not field:
            return True
        raw = record.get(field)
        if raw is None:
            return True
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("true", "yes", "1", "active")

    def _build_text(self, description: str, price: Any, code: str) -> str:
        parts: List[str] = []
        if description:
            parts.append(description.strip())
        if self.include_price and price not in (None, ""):
            parts.append(f"Price: {price}")
        if self.include_code and code:
            parts.append(f"Product code: {code}")
        return "\n\n".join(parts)

    def _category_parts(self, record: Dict[str, Any], slug: str) -> Tuple[str, str]:
        cat = ""
        field = self.fields.get("category")
        if field:
            raw = record.get(field)
            if isinstance(raw, dict):
                raw = raw.get("name") or raw.get("value")
            cat = str(raw or "")
        sub = ""
        attached_doc_id = self._slug_doc_ids.get(slug)
        if attached_doc_id:
            entry = self.existing_index.get(attached_doc_id) or {}
            cat = entry.get("category") or cat
            sub = entry.get("subcategory") or sub
        if not cat and not sub:
            cat = self.fallback_category
            sub = self.fallback_subcategory
        return str(cat or ""), str(sub or "")

    def process_record(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        id_field = self.fields.get("id") or "id"
        name_field = self.fields.get("name") or "Product_Name"
        text_field = self.fields.get("text") or "Description"
        url_field = self.fields.get("url") or "Website"
        price_field = self.fields.get("price") or "Unit_Price"
        code_field = self.fields.get("product_code") or "Product_Code"

        record_id = str(record.get(id_field) or "")
        name = str(record.get(name_field) or "").strip()
        if not name:
            return None
        if self.active_only and not self._is_active(record):
            return None

        description = str(record.get(text_field) or "").strip()
        price = record.get(price_field)
        code = str(record.get(code_field) or "").strip()
        text = self._build_text(description, price, code) or f"Information about {name}."

        slug = slugify(name)
        product_key = slug or f"zoho-{record_id or 'unknown'}"
        category, subcategory = self._category_parts(record, slug)

        attached_doc_id = self._slug_doc_ids.get(slug)
        url = record.get(url_field) if url_field else ""
        if isinstance(url, dict):
            url = url.get("name") or url.get("url") or ""
        url = str(url or "")

        doc_id = f"zoho:product:{product_key}"
        chunk_id = f"{doc_id}:catalogue:chunk:0.0"
        now = datetime.utcnow().isoformat()

        chunk: Dict[str, Any] = {
            "id": chunk_id,
            "chunk_type": "catalogue",
            "text": text,
            "section_kind": "content",
            "section_heading": "Product details",
            "section_index": 0,
            "doc_id": doc_id,
            "type": "product",
            "url": url,
            "title": name,
            "category": category,
            "subcategory": subcategory,
            "product_id": product_key,
            "article_id": "",
            "page_id": "",
            "scraped_at": now,
            "zoho_record_id": record_id,
            "zoho_source": "crm",
        }
        if attached_doc_id:
            chunk["attached_product_doc_id"] = attached_doc_id
        return chunk

    def process(
        self,
        records: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Convert records into (chunks, index_entries)."""
        chunks: List[Dict[str, Any]] = []
        index: Dict[str, Any] = {}
        for record in records:
            chunk = self.process_record(record)
            if not chunk:
                continue
            chunks.append(chunk)
            index[chunk["doc_id"]] = {
                "doc_id": chunk["doc_id"],
                "type": "product",
                "url": chunk.get("url") or "",
                "title": chunk["title"],
                "category": chunk.get("category") or "",
                "subcategory": chunk.get("subcategory") or "",
                "chunk_ids": [chunk["id"]],
                "product_key": chunk["product_id"],
                "zoho_record_id": chunk.get("zoho_record_id") or "",
                "attached_product_doc_id": chunk.get("attached_product_doc_id") or "",
            }
        return chunks, index
