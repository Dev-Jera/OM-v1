"""Orchestrate the Zoho CRM product sync into the RAG chunk pipeline.

Pulls products from Zoho CRM, converts them to chunks, then merges the
``zoho:`` chunks into ``data/processed/website_chunks.jsonl`` (idempotently)
and merges product entries into ``data/processed/website_index.json``. The
existing ``scripts/generate_embeddings.py`` step then embeds everything into
the configured vector store (Qdrant) as usual - nothing in the existing
pipeline is changed.

Credentials come from environment variables (ZOHO_CLIENT_ID,
ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN, ZOHO_REGION). Pass ``env_path`` to
load them from a file.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.integrations.zoho.collectors.crm_products import ZohoCRMProductsCollector
from src.integrations.zoho.oauth import ZohoTokenManager
from src.processors.zoho_crm_processor import ZohoCRMProcessor

logger = logging.getLogger(__name__)

ZOHO_PREFIX = "zoho:"


class ZohoSyncResult:
    def __init__(self, records: int = 0, chunks: int = 0, attached: int = 0, replaced: int = 0) -> None:
        self.records = records
        self.chunks = chunks
        self.attached = attached
        self.replaced = replaced


def _env(name: str, *, optional: bool = False, default: str = "") -> str:
    value = os.getenv(name, "")
    value = value.strip() if isinstance(value, str) else ""
    if not value and not optional:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value or default


def _load_fields_config(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        path = Path(__file__).parent.parent.parent.parent / "config" / "zoho_crm_fields.yml"
    if not path.exists():
        raise FileNotFoundError(f"Zoho fields config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_index(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _merge_zoho_chunks(chunks_path: Path, new_chunks: List[Dict[str, Any]]) -> int:
    """Replace all existing ``zoho:`` chunks with the fresh set.

    Every other line in the JSONL is kept byte-identical, so website/PDF
    chunks are untouched. Returns the number of replaced zoho lines.
    """
    kept: List[str] = []
    replaced = 0
    if chunks_path.exists():
        with open(chunks_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    kept.append(line)
                    continue
                doc_id = str(obj.get("doc_id") or "")
                if doc_id.startswith(ZOHO_PREFIX):
                    replaced += 1
                else:
                    kept.append(line)
    with open(chunks_path, "w", encoding="utf-8") as f:
        for line in kept:
            f.write(line + "\n")
        for chunk in new_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    return replaced


def _merge_index(index_path: Path, new_entries: Dict[str, Any]) -> None:
    index = _load_index(index_path)
    for doc_id, entry in new_entries.items():
        index[doc_id] = entry
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def run_zoho_sync(
    *,
    env_path: Optional[Path] = None,
    config_path: Optional[Path] = None,
    chunks_file: Optional[Path] = None,
    index_file: Optional[Path] = None,
    limit: Optional[int] = None,
) -> ZohoSyncResult:
    """Run the full Zoho product sync. Returns a ZohoSyncResult."""
    if env_path:
        from dotenv import load_dotenv

        load_dotenv(env_path)

    client_id = _env("ZOHO_CLIENT_ID")
    client_secret = _env("ZOHO_CLIENT_SECRET")
    refresh_token = _env("ZOHO_REFRESH_TOKEN")
    region = _env("ZOHO_REGION", optional=True, default="com")

    fields_config = _load_fields_config(config_path)
    fields_list = [
        v for v in (fields_config.get("fields") or {}).values() if isinstance(v, str)
    ]
    fields_list = list(dict.fromkeys(fields_list))

    chunks_path = chunks_file or Path("data/processed/website_chunks.jsonl")
    index_path = index_file or Path("data/processed/website_index.json")

    logger.info("Zoho sync: pulling products from %s", fields_config.get("module", "Products"))
    token_manager = ZohoTokenManager(client_id, client_secret, refresh_token, region=region)
    collector = ZohoCRMProductsCollector(
        token_manager,
        module=fields_config.get("module", "Products"),
        fields=fields_list,
    )
    records = collector.fetch_records(limit=limit)

    existing_index = _load_index(index_path)
    processor = ZohoCRMProcessor(fields_config, existing_index=existing_index)
    chunks, new_index_entries = processor.process(records)

    replaced = _merge_zoho_chunks(chunks_path, chunks)
    _merge_index(index_path, new_index_entries)

    attached = sum(1 for c in chunks if c.get("attached_product_doc_id"))
    logger.info(
        "Zoho sync done: %s product(s) pulled, %s chunk(s) written (%s attached to existing products), %s stale zoho chunk(s) replaced",
        len(records),
        len(chunks),
        attached,
        replaced,
    )
    return ZohoSyncResult(records=len(records), chunks=len(chunks), attached=attached, replaced=replaced)
