"""Admin data-ingestion pipeline endpoints.

Two-step flow per pipeline:
  1. Extract — runs the pipeline (scrape / fetch / process) and returns chunks
     for preview without writing to the shared KB files or the vector store.
  2. Ingest  — takes the previewed chunks, embeds them, and upserts into the
     vector store (Qdrant / pgvector) plus rebuilds the BM25 keyword index.

All endpoints are admin-protected and run heavy work in background threads so
the API response stays fast.
"""

from __future__ import annotations

import json
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from src.chatbot.dependencies import admin_auth_protection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/pipelines", tags=["Admin Pipelines"], dependencies=[Depends(admin_auth_protection)])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _read_chunks_from_jsonl(path: Path) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def _make_preview(chunks: List[Dict[str, Any]], limit: int = 20) -> List[Dict[str, Any]]:
    preview = []
    for c in chunks[:limit]:
        text = c.get("text") or ""
        preview.append({
            "id": c.get("id", ""),
            "doc_id": c.get("doc_id", ""),
            "title": c.get("title") or c.get("section_heading") or c.get("doc_id", ""),
            "type": c.get("type") or c.get("chunk_type") or "",
            "text_snippet": text[:200] + ("…" if len(text) > 200 else ""),
        })
    return preview


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    chunks: List[Dict[str, Any]]
    source_type: str = "manual"


class IngestResponse(BaseModel):
    status: str
    ingested: int


# ---------------------------------------------------------------------------
# 1. Website scrape → extract
# ---------------------------------------------------------------------------

@router.post("/website-scrape/extract")
async def website_scrape_extract():
    """Full scrape of the OM website + process into chunks. Returns preview."""

    def _run() -> Dict[str, Any]:
        from src.scrapers.website_scraper import OldMutualWebsiteScraper
        from src.processors.website_processor import WebsiteProcessor
        from src.utils.processing_config_loader import load_processing_config

        with tempfile.TemporaryDirectory(prefix="pipeline_ws_") as tmp:
            tmp_path = Path(tmp)
            raw_path = tmp_path / "raw.json"
            out_path = tmp_path / "processed"

            # Scrape
            scraper = OldMutualWebsiteScraper(output_dir=str(tmp_path))
            raw_data = scraper.scrape()
            raw_path.write_text(json.dumps(raw_data, ensure_ascii=False), encoding="utf-8")

            # Process
            config = load_processing_config()
            processor = WebsiteProcessor(config)
            stats = processor.process(raw_path, output_dir=out_path)

            chunks_path = out_path / "website_chunks.jsonl"
            if not chunks_path.exists():
                return {"chunks": [], "count": 0, "preview": [], "stats": {
                    "pages_scraped": scraper.stats.get("total_scraped", 0),
                    "valid_content": scraper.stats.get("valid_content", 0),
                }}

            chunks = _read_chunks_from_jsonl(chunks_path)
            return {
                "chunks": chunks,
                "count": len(chunks),
                "preview": _make_preview(chunks),
                "stats": {
                    "pages_scraped": scraper.stats.get("total_scraped", 0),
                    "valid_content": scraper.stats.get("valid_content", 0),
                    "documents_written": stats.documents_written,
                    "chunks_written": stats.chunks_written,
                },
            }

    import asyncio
    return await asyncio.to_thread(_run)


# ---------------------------------------------------------------------------
# 2. Zoho CRM → extract
# ---------------------------------------------------------------------------

@router.post("/zoho/extract")
async def zoho_extract():
    """Fetch products from Zoho CRM and process into chunks. Returns preview."""

    def _run() -> Dict[str, Any]:
        import os
        import yaml
        from src.integrations.zoho.oauth import ZohoTokenManager
        from src.integrations.zoho.collectors.crm_products import ZohoCRMProductsCollector
        from src.processors.zoho_crm_processor import ZohoCRMProcessor

        client_id = os.getenv("ZOHO_CLIENT_ID", "").strip()
        client_secret = os.getenv("ZOHO_CLIENT_SECRET", "").strip()
        refresh_token = os.getenv("ZOHO_REFRESH_TOKEN", "").strip()
        region = os.getenv("ZOHO_REGION", "com").strip().lower()

        if not client_id or not client_secret or not refresh_token:
            raise HTTPException(status_code=403, detail="Zoho credentials not configured")

        fields_path = Path("config/zoho_crm_fields.yml")
        with open(fields_path, "r", encoding="utf-8") as f:
            fields_config = yaml.safe_load(f) or {}
        fields_list = [v for v in (fields_config.get("fields") or {}).values() if isinstance(v, str)]
        fields_list = list(dict.fromkeys(fields_list))

        token_manager = ZohoTokenManager(client_id, client_secret, refresh_token, region=region)
        collector = ZohoCRMProductsCollector(
            token_manager,
            module=fields_config.get("module", "Products"),
            fields=fields_list,
        )
        records = collector.fetch_records()

        # Load existing index for attachment logic
        index_path = Path("data/processed/website_index.json")
        existing_index = {}
        if index_path.exists():
            existing_index = json.loads(index_path.read_text(encoding="utf-8"))

        processor = ZohoCRMProcessor(fields_config, existing_index=existing_index)
        chunks, new_index_entries = processor.process(records)

        return {
            "chunks": chunks,
            "count": len(chunks),
            "preview": _make_preview(chunks),
            "stats": {
                "records_fetched": len(records),
                "chunks_produced": len(chunks),
            },
        }

    import asyncio
    return await asyncio.to_thread(_run)


# ---------------------------------------------------------------------------
# 3. PDF upload → extract
# ---------------------------------------------------------------------------

@router.post("/pdf/extract")
async def pdf_extract(file: UploadFile = File(...), title: Optional[str] = Form(default=None)):
    """Process an uploaded PDF into chunks. Returns preview."""

    def _run(pdf_path_str: str, upload_title: Optional[str]) -> Dict[str, Any]:
        from src.processors.pdf_catalogue_processor import PDFCatalogueProcessor

        pdf_path = Path(pdf_path_str)
        processor = PDFCatalogueProcessor()

        with tempfile.TemporaryDirectory(prefix="pipeline_pdf_") as tmp:
            out_path = Path(tmp)
            stats = processor.process(
                pdf_path,
                output_dir=out_path,
                title=upload_title or pdf_path.stem,
            )
            chunks_path = out_path / "pdf_catalogue_chunks.jsonl"
            if not chunks_path.exists():
                return {"chunks": [], "count": 0, "preview": [], "stats": {}}

            chunks = _read_chunks_from_jsonl(chunks_path)
            return {
                "chunks": chunks,
                "count": len(chunks),
                "preview": _make_preview(chunks),
                "stats": {
                    "pages_processed": stats.pages_processed,
                    "chunks_written": stats.chunks_written,
                },
            }

    upload_dir = Path(tempfile.gettempdir()) / "pipeline_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"{uuid.uuid4().hex}_{file.filename or 'upload.pdf'}"
    content = await file.read()
    dest.write_bytes(content)

    import asyncio
    return await asyncio.to_thread(_run, str(dest), title)


# ---------------------------------------------------------------------------
# 4. Paste text → extract
# ---------------------------------------------------------------------------

@router.post("/text/extract")
async def text_extract(body: Dict[str, Any]):
    """Process pasted raw text into chunks. Returns preview."""
    text = (body.get("text") or "").strip()
    title = body.get("title") or "Pasted Knowledge"
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    def _run(text_content: str, extract_title: str) -> Dict[str, Any]:
        from src.processors.text_processor import TextFileProcessor

        processor = TextFileProcessor()

        with tempfile.TemporaryDirectory(prefix="pipeline_text_") as tmp:
            tmp_path = Path(tmp)
            text_file = tmp_path / "pasted.txt"
            text_file.write_text(text_content, encoding="utf-8")

            out_path = tmp_path / "processed"
            stats = processor.process(
                text_file,
                output_dir=out_path,
                title=extract_title,
            )
            chunks_path = out_path / "text_knowledge_chunks.jsonl"
            if not chunks_path.exists():
                return {"chunks": [], "count": 0, "preview": [], "stats": {}}

            chunks = _read_chunks_from_jsonl(chunks_path)
            return {
                "chunks": chunks,
                "count": len(chunks),
                "preview": _make_preview(chunks),
                "stats": {
                    "text_length": stats.text_length_chars,
                    "chunks_written": stats.chunks_written,
                },
            }

    import asyncio
    return await asyncio.to_thread(_run, text, title)


# ---------------------------------------------------------------------------
# 5. Ingest chunks → vector DB + BM25
# ---------------------------------------------------------------------------

@router.post("/ingest", response_model=IngestResponse)
async def ingest_to_vectordb(body: IngestRequest):
    """Embed chunks and upsert into the vector store. Rebuilds BM25 index."""

    def _run(chunks: List[Dict[str, Any]], source_type: str) -> int:
        from src.utils.rag_config_loader import load_rag_config
        from src.rag.ingest import ingest_chunks_to_qdrant
        from src.rag.keyword_search import BM25KeywordSearch

        cfg = load_rag_config()

        with tempfile.TemporaryDirectory(prefix="pipeline_ingest_") as tmp:
            chunks_file = Path(tmp) / "chunks.jsonl"
            with open(chunks_file, "w", encoding="utf-8") as f:
                for c in chunks:
                    f.write(json.dumps(c, ensure_ascii=False) + "\n")

            ingested = ingest_chunks_to_qdrant(chunks_file, cfg)

            # Rebuild BM25 from the main chunks file
            main_chunks = Path("data/processed/website_chunks.jsonl")
            if main_chunks.exists():
                bm25 = BM25KeywordSearch()
                bm25.build_index(main_chunks)
                logger.info("BM25 index rebuilt after %s ingest (%d chunks)", source_type, ingested)

            return ingested

    import asyncio
    count = await asyncio.to_thread(_run, body.chunks, body.source_type)
    return IngestResponse(status="ok", ingested=count)
