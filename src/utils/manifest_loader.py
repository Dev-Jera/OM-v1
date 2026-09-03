"""
Manifest loader — provides per-product section awareness for the chatbot.

Loads data/processed/structured/_all_manifests.json at startup and
exposes fast lookup functions so the bot knows which information
sections exist for each product, and can respond honestly when a
section is missing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MANIFESTS_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "structured" / "_all_manifests.json"

_manifests: Dict[str, Dict[str, Any]] = {}
_loaded = False


def load_manifests(path: Optional[Path] = None) -> int:
    """Load the combined manifest index into memory. Returns number of products."""
    global _manifests, _loaded
    manifest_path = path or _MANIFESTS_PATH
    if not manifest_path.exists():
        logger.warning("Manifest file not found: %s", manifest_path)
        _manifests = {}
        _loaded = True
        return 0
    with open(manifest_path, "r", encoding="utf-8") as f:
        _manifests = json.load(f)
    _loaded = True
    logger.info("Loaded manifests for %s products from %s", len(_manifests), manifest_path)
    return len(_manifests)


def _ensure_loaded() -> None:
    if not _loaded:
        load_manifests()


def get_manifest(product_id: str) -> Optional[Dict[str, Any]]:
    """Return the manifest for a product, or None if not found."""
    _ensure_loaded()
    return _manifests.get(product_id)


def get_sections(product_id: str) -> List[str]:
    """Return the list of available section names for a product."""
    manifest = get_manifest(product_id)
    if not manifest:
        return []
    return manifest.get("sections", [])


def get_section_counts(product_id: str) -> Dict[str, int]:
    """Return a dict of {section: chunk_count} for a product."""
    manifest = get_manifest(product_id)
    if not manifest:
        return {}
    return manifest.get("section_counts", {})


def has_section(product_id: str, section: str) -> bool:
    """Check whether a specific section exists for a product."""
    return section in get_sections(product_id)


def get_missing_sections(product_id: str) -> List[str]:
    """Return the list of missing section names for a product."""
    manifest = get_manifest(product_id)
    if not manifest:
        return []
    return manifest.get("missing_sections", [])


def list_products() -> List[str]:
    """Return all product IDs that have manifests."""
    _ensure_loaded()
    return sorted(_manifests.keys())
