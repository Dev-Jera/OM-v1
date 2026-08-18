# Zoho CRM Extraction

Plain-English description of how product records are pulled out of **Zoho CRM** and fed into the same knowledge base (Qdrant) that MIA answers from — without touching the existing website/PDF pipeline.

## The flow at a glance

```
Zoho CRM (Products module)
     -> OAuth refresh-token flow (get an access token)
     -> collector pulls product records (paginated)
     -> processor turns each record into a standard chunk
     -> sync merges the chunks into website_chunks.jsonl + website_index.json
     -> generate_embeddings.py embeds everything into Qdrant as usual
```

The key idea: Zoho products become **ordinary chunks with a `zoho:` doc_id prefix**. From the embedding step onward, the existing pipeline does all the work — nothing in it was changed.

## Step by step

### 1. Authentication (OAuth refresh-token flow)
`src/integrations/zoho/oauth.py` -> `ZohoTokenManager`

- Uses a long-lived **refresh token** to request short-lived access tokens from `accounts.zoho.com` (region-aware: `.com`, `.eu`, `.in`, `.au`, `.jp`).
- Caches the access token until ~60s before expiry, so most API calls reuse it.
- If a call ever gets a `401`, it forces one refresh and retries.
- Credentials come from environment variables (never committed): `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`, `ZOHO_REGION`.

### 2. Pulling the records
`src/integrations/zoho/collectors/crm_products.py` -> `ZohoCRMProductsCollector`

- Calls `GET /crm/v2/Products` with the field list from the config.
- Pages through results 200 records at a time until `more_records` is false.
- Raises `ZohoCRMError` on any non-recoverable HTTP failure.

### 3. Turning records into chunks
`src/processors/zoho_crm_processor.py` -> `ZohoCRMProcessor`

- Maps CRM fields to canonical chunk fields using `config/zoho_crm_fields.yml` (which CRM column is the name, description, category, price, etc. — production differences are a config swap, not a code change).
- Skips inactive records (when `active_only` is set) and records without a name.
- Produces chunks in the **exact same schema** as website product chunks:
  - `doc_id`: `zoho:product:<slugified-name>`
  - `id`: `zoho:product:<slug>:catalogue:chunk:0.0`
  - `type`: `product`, `chunk_type`: `catalogue`
  - `text`: the description (plus price when `include_price_in_text` is on)
  - `zoho_record_id` / `zoho_source`: traceability back to the CRM record
- **Attach logic**: if a website product with the same title already exists in the index, the zoho chunk records `attached_product_doc_id` and inherits its category/subcategory — so CRM data reinforces the website product instead of floating alone.

### 4. Merging into the knowledge base files
`src/integrations/zoho/sync.py` -> `run_zoho_sync` (CLI: `scripts/run_zoho_sync.py`)

- Reads `data/processed/website_chunks.jsonl`, **keeps every non-zoho line byte-identical**, drops all existing `zoho:` lines, and appends the fresh ones. Re-running never duplicates.
- Does the same for `data/processed/website_index.json` (removes old `zoho:` entries, adds fresh ones).
- Prints a summary: records pulled, chunks written, attached count, stale chunks replaced.

### 5. Embedding into Qdrant
`scripts/generate_embeddings.py` — unchanged. It reads `website_chunks.jsonl` and upserts every chunk (website, PDF, and now `zoho:`) into the Qdrant collection (`Mia-chatbot`). MIA then retrieves Zoho product knowledge exactly like any other chunk.

## Why this is safe to re-run

- `scripts/run_processing.py` only rewrites chunks whose `doc_id` starts with `website:` — anything else (including `zoho:`) is preserved across website re-scrapes.
- `run_zoho_sync.py` replaces the whole `zoho:` set on every run — idempotent by design.
- Embeddings are upserted keyed by chunk `id` — no duplicates in Qdrant.

## Where it runs

### GitHub workflow
`.github/workflows/data-pipeleine.yml` has a **"Sync Zoho CRM products"** step right after "Run pipeline": it runs `run_zoho_sync.py` then `generate_embeddings.py` again. The step **skips automatically** when `ZOHO_CLIENT_ID` is not set, so the pipeline behaves exactly as before until credentials are added as repo secrets.

### Admin endpoint
`POST /api/v1/admin/sync/zoho` (`src/api/main.py`) triggers a sync on demand. It is protected by `admin_auth_protection` and only active when `ZOHO_SYNC_ENABLED=true`.

## One-time credential setup

1. In [api-console.zoho.com](https://api-console.zoho.com) create a **Server-based Application**.
   - Homepage URL: `http://localhost:8080`
   - Authorized Redirect URI: `http://localhost:8080` (must match exactly)
2. Put `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REGION` into `.env`.
3. Mint the refresh token (scope `ZohoCRM.modules.products.READ` — least privilege):

   ```
   python scripts/zoho_oauth_setup.py --env .env --write
   ```

   A browser opens the Zoho consent screen; after approval the refresh token is written into `.env` automatically.

## Running a sync locally

```
python scripts/run_zoho_sync.py --env .env            # pull + merge
python scripts/generate_embeddings.py --config config/rag_config.yml   # embed into Qdrant
```

Optional flags on the sync script: `--limit N` (pull only N records, handy for testing), `--chunks-file` / `--index-file` (alternate output paths).

## Tests

24 fixture-based tests (no network calls):

- `tests/test_zoho_oauth.py` — token refresh, caching, forced refresh, region handling
- `tests/test_zoho_crm_collector.py` — pagination, field selection, 401 retry, errors
- `tests/test_zoho_crm_processor.py` — chunk schema, slugify, active filter, attach logic
- `tests/test_zoho_sync.py` — merge preserves website lines, idempotency, limit, missing creds

## File map

| File | Role |
| --- | --- |
| `src/integrations/zoho/oauth.py` | Token manager (refresh, cache, region-aware) |
| `src/integrations/zoho/collectors/crm_products.py` | Paginated Products API collector |
| `src/processors/zoho_crm_processor.py` | Record -> chunk conversion + attach logic |
| `src/integrations/zoho/sync.py` | Idempotent merge orchestration |
| `scripts/run_zoho_sync.py` | CLI entry point |
| `scripts/zoho_oauth_setup.py` | One-time refresh-token minting |
| `config/zoho_crm_fields.yml` | CRM field mapping (production = config swap) |
