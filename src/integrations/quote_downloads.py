"""Shared storage for generated quote PDFs and quote metadata.

Uses in-memory caches for fast access and a disk-backed store so quote data
survives process restarts (e.g. Swagger testing with reload/redeploy).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

_quotes_store: Dict[str, Dict[str, Any]] = {}
_pdf_store: Dict[str, bytes] = {}


def _storage_dir() -> Path:
    root = os.getenv("QUOTE_STORAGE_DIR", "data/processed/quote_downloads")
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_quote_id(quote_id: str) -> str:
    return "".join(ch for ch in str(quote_id) if ch.isalnum() or ch in {"-", "_"}) or "unknown"


def _metadata_path(quote_id: str) -> Path:
    return _storage_dir() / f"{_safe_quote_id(quote_id)}.json"


def _pdf_path(quote_id: str) -> Path:
    return _storage_dir() / f"{_safe_quote_id(quote_id)}.pdf"


def build_download_url(quote_id: str) -> str:
    """Return the API path used by the frontend to download a quote PDF."""
    return f"/api/v1/products/quotes/{quote_id}/download"


def register_quote_pdf(
    quote_id: str,
    pdf_bytes: Optional[bytes] = None,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Store generated PDF bytes and return the download URL."""
    quote_key = str(quote_id)

    if pdf_bytes is not None:
        _pdf_store[quote_key] = pdf_bytes
        _pdf_path(quote_key).write_bytes(pdf_bytes)

    if metadata:
        merged: Dict[str, Any] = {}
        existing = get_quote_metadata(quote_key)
        if existing:
            merged.update(existing)
        merged.update(metadata)
        _quotes_store[quote_key] = merged
        _metadata_path(quote_key).write_text(json.dumps(merged, ensure_ascii=True), encoding="utf-8")

    return build_download_url(quote_key)


def get_quote_pdf(quote_id: str) -> Optional[bytes]:
    quote_key = str(quote_id)
    cached = _pdf_store.get(quote_key)
    if cached is not None:
        return cached

    path = _pdf_path(quote_key)
    if not path.exists():
        return None

    data = path.read_bytes()
    _pdf_store[quote_key] = data
    return data


def get_quote_metadata(quote_id: str) -> Optional[Dict[str, Any]]:
    quote_key = str(quote_id)
    cached = _quotes_store.get(quote_key)
    if cached is not None:
        return cached

    path = _metadata_path(quote_key)
    if not path.exists():
        return None

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if isinstance(loaded, dict):
        _quotes_store[quote_key] = loaded
        return loaded
    return None
