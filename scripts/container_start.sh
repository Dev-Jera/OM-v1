#!/usr/bin/env sh
set -eu

if [ "${USE_ALEMBIC_MIGRATIONS:-true}" = "true" ]; then
  echo "[startup] Running database migrations..."
  alembic upgrade head
fi

if [ "${RUN_PDF_CATALOGUE_INGEST_ON_START:-true}" = "true" ]; then
  PDF_PATH="${PDF_CATALOGUE_PATH:-data/raw/pdf/Insurance Product Catalogue (1).pdf}"

  if [ -f "$PDF_PATH" ]; then
    echo "[startup] Running PDF catalogue ingestion into vector store..."
    if python scripts/add_pdf_catalogue_to_kb.py \
      --pdf-path "$PDF_PATH" \
      --skip-append \
      --skip-bm25 \
      --skip-vector-if-doc-exists; then
      echo "[startup] PDF catalogue ingestion step completed."
    else
      if [ "${FAIL_ON_PDF_CATALOGUE_INGEST_ERROR:-false}" = "true" ]; then
        echo "[startup] PDF ingestion failed and FAIL_ON_PDF_CATALOGUE_INGEST_ERROR=true, exiting."
        exit 1
      fi
      echo "[startup] PDF ingestion failed, continuing to API startup."
    fi
  else
    echo "[startup] PDF catalogue not found at '$PDF_PATH'. Skipping ingestion."
  fi
else
  echo "[startup] RUN_PDF_CATALOGUE_INGEST_ON_START=false, skipping PDF ingestion."
fi

echo "[startup] Building BM25 keyword index..."
if python scripts/build_bm25_index.py; then
  echo "[startup] BM25 index ready."
else
  echo "[startup] BM25 index build skipped/failed (non-fatal)."
fi

echo "[startup] Starting API server..."
exec uvicorn src.api.main:app --host 0.0.0.0 --port 8000
