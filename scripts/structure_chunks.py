#!/usr/bin/env python3
"""
Structure existing website chunks into per-product, section-tagged files.

Reads data/processed/website_chunks.jsonl, tags each chunk with a
standardized section name, and writes:
  - data/processed/structured/<product_id>.jsonl  (per-product chunks)
  - data/processed/structured/<product_id>_manifest.json  (per-product manifest)
  - data/processed/structured/_all_manifests.json  (combined index)

Run once after initial processing. Re-run after new scrapes to keep
structured files in sync.

Usage:
    python scripts/structure_chunks.py
    python scripts/structure_chunks.py --chunks-file data/processed/website_chunks.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section mapping: chunk_type + section_heading → standardized section name
# ---------------------------------------------------------------------------

# Direct chunk_type mappings (no heading lookup needed)
_CHUNK_TYPE_MAP: Dict[str, str] = {
    "overview": "overview",
    "benefits": "benefits",
    "faq": "faqs",
    "application": "process",
    "payment_methods": "payment_methods",
    "eligibility": "eligibility",
    "coverage": "coverage",
    "exclusions": "exclusions",
    "pricing": "pricing",
}

# Heading keyword → section (used when chunk_type is "general" / unclassified)
_HEADING_KEYWORDS: list[tuple[list[str], str]] = [
    (["what is", "what's the", "who we are", "about"], "overview"),
    (["benefit", "what's in it", "whats in it", "feature"], "benefits"),
    (
        [
            "how do i apply",
            "how i do apply",
            "how do i become",
            "application",
            "first time",
            "how do i claim",
            "claim",
            "complaints",
        ],
        "process",
    ),
    (["payment", "pay premium", "banking option"], "payment_methods"),
    (
        ["eligible", "who can", "requirements", "who is it for", "what are the requirements"],
        "eligibility",
    ),
    (["coverage", "what is covered", "what's covered", "what does it cover", "region"], "coverage"),
    (
        ["exclusion", "not covered", "what cannot be covered", "what's excluded", "what is excluded"],
        "exclusions",
    ),
    (["premium", "price", "cost", "how much", "tax", "rate of return"], "pricing"),
    (
        [
            "login",
            "portal",
            "access",
            "top up",
            "withdraw",
            "monitor",
            "how quickly can i access",
            "service provider",
            "role of",
        ],
        "manage",
    ),
    (["where", "branch", "office", "location", "head office", "satellite", "outlet"], "service_channels"),
    (["contact", "phone", "email", "get in touch", "toll free", "call us"], "contacts"),
    (["link", "url", "website", "portal"], "links"),
    (["error", "mistake", "wrong", "problem", "complaint"], "errors"),
    (["what if", "scenario", "situation", "what happens if"], "scenarios"),
    (["how does it work", "how do", "step by step", "process"], "process"),
]


def _normalize_section_heading(heading: str) -> str:
    return re.sub(r"\s+", " ", (heading or "")).strip().lower()


def _resolve_section_from_heading(heading: str) -> Optional[str]:
    h = _normalize_section_heading(heading)
    if not h:
        return None
    for keywords, section in _HEADING_KEYWORDS:
        if any(kw in h for kw in keywords):
            return section
    return None


def _resolve_section(chunk: Dict[str, Any]) -> str:
    """Map a chunk to its standardized section name."""
    chunk_type = (chunk.get("chunk_type") or "").strip().lower()
    heading = (chunk.get("section_heading") or "").strip()

    # 1. Direct chunk_type mapping
    if chunk_type in _CHUNK_TYPE_MAP:
        return _CHUNK_TYPE_MAP[chunk_type]

    # 2. Heading-based lookup for unclassified chunks
    if chunk_type in ("general", "article_section", "info_section", ""):
        mapped = _resolve_section_from_heading(heading)
        if mapped:
            return mapped

    # 3. Fallback
    return "general"


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------


def _load_chunks(chunks_path: Path) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSON line %s", line_num)
                continue
            if not isinstance(chunk, dict):
                continue
            chunks.append(chunk)
    return chunks


def _group_by_product(chunks: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        pid = (chunk.get("product_id") or "").strip()
        if not pid:
            pid = "_unassigned"
        groups[pid].append(chunk)
    return dict(groups)


def _build_manifest(
    product_id: str,
    chunks: List[Dict[str, Any]],
    product_documents: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a manifest dict for one product."""
    section_counts: Dict[str, int] = defaultdict(int)
    for chunk in chunks:
        section = chunk.get("section", "general")
        section_counts[section] += 1

    # Extract metadata from website_documents if available
    doc = product_documents.get(product_id, {})
    product_name = doc.get("title") or product_id.replace("-", " ").title()
    category = doc.get("category", "")
    subcategory = doc.get("subcategory", "")
    source_url = doc.get("url", "")

    all_sections = [
        "overview",
        "benefits",
        "faqs",
        "process",
        "eligibility",
        "pricing",
        "coverage",
        "exclusions",
        "payment_methods",
        "manage",
        "service_channels",
        "contacts",
        "links",
        "scenarios",
        "errors",
        "general",
    ]
    available = [s for s in all_sections if section_counts.get(s, 0) > 0]
    missing = [s for s in all_sections if section_counts.get(s, 0) == 0 and s != "general"]

    return {
        "product_id": product_id,
        "product_name": product_name,
        "category": category,
        "subcategory": subcategory,
        "source_url": source_url,
        "total_chunks": len(chunks),
        "sections": available,
        "section_counts": dict(section_counts),
        "missing_sections": missing,
    }


def _load_product_documents(documents_path: Path) -> Dict[str, Any]:
    """Load website_documents.jsonl and index by product_id."""
    docs: Dict[str, Any] = {}
    with open(documents_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(doc, dict):
                continue
            pid = (doc.get("product_id") or "").strip()
            if pid:
                docs[pid] = doc
    return docs


def structure_chunks(
    chunks_path: Path,
    output_dir: Path,
) -> Dict[str, int]:
    """Main entry: read chunks, tag sections, write structured output."""
    output_dir.mkdir(parents=True, exist_ok=True)

    chunks = _load_chunks(chunks_path)
    logger.info("Loaded %s chunks from %s", len(chunks), chunks_path)

    # Tag each chunk with standardized section
    for chunk in chunks:
        chunk["section"] = _resolve_section(chunk)

    # Load product documents for metadata
    documents_path = chunks_path.parent / "website_documents.jsonl"
    product_docs = _load_product_documents(documents_path) if documents_path.exists() else {}

    # Group by product_id
    groups = _group_by_product(chunks)
    logger.info("Grouped into %s products", len(groups))

    all_manifests: Dict[str, Any] = {}
    total_written = 0

    for pid, product_chunks in sorted(groups.items()):
        # Write per-product chunks
        product_file = output_dir / f"{pid}.jsonl"
        with open(product_file, "w", encoding="utf-8") as f:
            for chunk in product_chunks:
                f.write(json.dumps(chunk, ensure_ascii=False, default=str) + "\n")

        # Build and write manifest
        manifest = _build_manifest(pid, product_chunks, product_docs)
        manifest_file = output_dir / f"{pid}_manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        all_manifests[pid] = manifest
        total_written += len(product_chunks)

        # Log summary
        sections = ", ".join(
            f"{s}:{c}" for s, c in sorted(manifest["section_counts"].items())
        )
        logger.info("  %s: %s chunks [%s]", pid, len(product_chunks), sections)

    # Write combined manifest index
    all_manifests_path = output_dir / "_all_manifests.json"
    with open(all_manifests_path, "w", encoding="utf-8") as f:
        json.dump(all_manifests, f, indent=2, ensure_ascii=False)

    logger.info("Written %s chunks across %s products to %s", total_written, len(groups), output_dir)
    return {"chunks": total_written, "products": len(groups)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Structure chunks into per-product files.")
    parser.add_argument(
        "--chunks-file",
        type=Path,
        default=Path("data/processed/website_chunks.jsonl"),
        help="Path to website_chunks.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed/structured"),
        help="Output directory for structured files",
    )
    args = parser.parse_args()

    if not args.chunks_file.exists():
        raise FileNotFoundError(f"Chunks file not found: {args.chunks_file}")

    stats = structure_chunks(args.chunks_file, args.output_dir)
    logger.info("Done: %s", stats)


if __name__ == "__main__":
    raise SystemExit(main())
