# Technical Manual

## 1. Project Overview

This repository implements a hybrid Retrieval-Augmented Generation (RAG) system for Old Mutual Uganda's insurance and investment ecosystem. It combines:

- document ingestion and semantic search,
- conversational product discovery,
- guided multi-step quote flows,
- quote, underwriting, payment, and policy integrations,
- admin and analytics endpoints for operational visibility.

The system is designed to support product consultation, quote generation, and structured form submission across multiple products such as Motor Private, Travel Insurance, Personal Accident, and Serenicare.

## 2. Runtime Architecture

### 2.1 Primary Entry Points

- FastAPI app: [src/api/main.py](src/api/main.py)
- Docker startup: [Dockerfile](Dockerfile)
- Process file for deployment: [Procfile](Procfile)
- Data pipeline scripts: [scripts/](scripts/)

The API is the main runtime. The scripts folder supports the offline pipeline for scraping, processing, embedding, and testing.

### 2.2 Major Layers

- API layer: HTTP endpoints, session handling, metrics, and admin routes.
- Chatbot layer: conversational and guided insurance flows.
- RAG layer: retrieval, reranking, and text generation.
- Integration layer: mock and real partner integrations.
- Database layer: PostgreSQL-backed or in-memory storage, plus Redis cache.
- Scraping and processing layer: website crawling, content cleaning, and chunk generation.

## 3. Repository Layout

### 3.1 Important Paths

- [src/api/](src/api/): FastAPI routes and request handling.
- [src/chatbot/](src/chatbot/): conversational mode, guided flows, validators, routers, and state.
- [src/rag/](src/rag/): retrieval, embeddings, and generation.
- [src/integrations/](src/integrations/): quote, underwriting, payment, policy, and mock clients.
- [src/database/](src/database/): ORM models and database adapters.
- [src/processors/](src/processors/): content cleaning and document processing.
- [src/utils/](src/utils/): config loading, matching, and runtime helpers.
- [tests/](tests/): automated tests.
- [scripts/](scripts/): operational scripts and manual test helpers.
- [config/](config/): scraping, processing, RAG, and synonym configuration.
- [docs/](docs/): implementation guides and process notes.

### 3.2 Key Documentation

- [README.md](README.md)
- [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)
- [QUOTES_UNDERWRITING_API.md](QUOTES_UNDERWRITING_API.md)
- [SCRAPER_USAGE.md](SCRAPER_USAGE.md)
- [docs/FLOW_REFACTORING_PATTERN.md](docs/FLOW_REFACTORING_PATTERN.md)
- [docs/VALIDATION_UX_FLOW.md](docs/VALIDATION_UX_FLOW.md)

## 4. Environment Setup

### 4.1 Requirements

- Python 3.11+
- Virtual environment recommended
- Dependencies in [requirements.txt](requirements.txt) and [requirements-dev.txt](requirements-dev.txt)

### 4.2 Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 4.3 Runtime Configuration

Important environment variables include:

- `API_KEYS` for API access protection
- `DATABASE_URL` for real PostgreSQL usage
- `REDIS_URL` for Redis caching
- `USE_POSTGRES_CONVERSATIONS` to enable real Postgres conversation storage
- `USE_REDIS_CONNECTIONS` to enable Redis-backed connections
- `INTEGRATIONS_MODE` to switch between mock and real partner integrations
- `SERVICE_HEARTBEAT_ENABLED` and `SERVICE_HEARTBEAT_INTERVAL_SECONDS` for health metrics

The app auto-detects whether to use real or in-memory services through [src/utils/runtime_env.py](src/utils/runtime_env.py).

## 5. How the System Works

### 5.1 Chat and RAG Flow

1. A user sends a chat message to the API.
2. The chatbot router decides whether to handle it conversationally or as a guided flow.
3. Conversational mode uses product matching and RAG retrieval to find relevant content.
4. The generation layer produces the final answer.
5. Conversation state and messages are stored through the database adapter.

### 5.2 Guided Product Flows

Guided mode supports structured, step-based flows for quote collection and underwriting. The main flows currently include:

- `personal_accident`
- `motor_private`
- `travel_insurance`
- `serenicare`
- `journey`
- `discovery`
- `payment`

The flow registry lives in [src/chatbot/flows/registry.py](src/chatbot/flows/registry.py), with flow implementations under [src/chatbot/flows/](src/chatbot/flows/).

### 5.3 Product Data Pipeline

The offline pipeline is usually:

1. scrape website content,
2. clean and process the content,
3. generate embeddings,
4. index the chunks for retrieval.

Relevant configuration is in [config/scraping_config.yml](config/scraping_config.yml), [config/processing_config.yml](config/processing_config.yml), and [config/rag_config.yml](config/rag_config.yml).

## 6. API Reference

The main API is versioned under `/api/v1`.

### 6.1 Chat and Sessions

- `POST /api/v1/session`
- `GET /api/v1/session/{session_id}`
- `POST /api/v1/chat/message`
- `POST /api/v1/chat/start-guided`

### 6.2 General Information

- `GET /api/v1/general-information`

This endpoint serves structured product information from JSON files in [general_information/product_json/](general_information/product_json/). It returns product fields like definition, benefits, and eligibility, plus structured section output for readability.

### 6.3 Product APIs

- `GET /api/v1/products/list`
- `GET /api/v1/products/card/{product_id}`
- `GET /api/v1/products/card/{product_id}/details`
- `GET /api/v1/products/quotes/{quote_id}/download`

### 6.4 Forms

- `POST /api/v1/forms/personal-accident/full`
- `POST /api/v1/forms/motor-private/full`
- `POST /api/v1/forms/travel-insurance/full`
- `POST /api/v1/forms/serenicare/full`
- `GET /api/v1/forms/draft/{session_id}/{flow_name}`
- `DELETE /api/v1/forms/draft/{session_id}/{flow_name}`

### 6.5 Metrics and Admin

- `GET /api/v1/metrics/rag`
- `GET /api/v1/metrics/system-performance`
- `GET /api/v1/metrics/ai-performance`
- `POST /api/v1/metrics/csat`
- `GET /api/v1/admin/chat-console/queue`
- `GET /api/v1/admin/chat-console/conversations/{session_id}`
- `POST /api/v1/admin/chat-console/conversations/{session_id}/reply`

## 7. Core Modules

### 7.1 API Layer

The API app is assembled in [src/api/main.py](src/api/main.py). It wires together:

- FastAPI app creation and middleware
- auth dependencies
- RAG adapter bootstrapping
- route registration
- session management
- metrics collection
- admin console support

### 7.2 Chatbot Layer

- [src/chatbot/modes/conversational.py](src/chatbot/modes/conversational.py): free-form chat, intent detection, product matching, and response shaping
- [src/chatbot/modes/guided.py](src/chatbot/modes/guided.py): flow selection and state transitions
- [src/chatbot/state_manager.py](src/chatbot/state_manager.py): session and flow state storage
- [src/chatbot/dependencies.py](src/chatbot/dependencies.py): authentication helpers and admin token handling

### 7.3 RAG Layer

- [src/rag/query.py](src/rag/query.py): retrieval pipeline and reranking
- [src/rag/generate.py](src/rag/generate.py): generation orchestration and fallback handling
- [src/rag/embeddings/embedder.py](src/rag/embeddings/embedder.py): embedding providers

### 7.4 Integrations

- [src/integrations/product_benefits.py](src/integrations/product_benefits.py): product benefits and config loading
- [src/integrations/quote_downloads.py](src/integrations/quote_downloads.py): quote PDF storage and metadata retrieval
- [src/integrations/policy/](src/integrations/policy/): policy and underwriting journey logic
- [src/integrations/payments/](src/integrations/payments/): payment integration support
- [src/integrations/clients/mocks/](src/integrations/clients/mocks/): test doubles and mock clients

### 7.5 Database

- [src/database/models.py](src/database/models.py): ORM models
- [src/database/postgres.py](src/database/postgres.py): in-memory adapter used for local development
- [src/database/postgres_real.py](src/database/postgres_real.py): SQLAlchemy/PostgreSQL adapter
- [src/database/redis.py](src/database/redis.py): in-memory cache
- [src/database/redis_real.py](src/database/redis_real.py): Redis-backed cache

## 8. Data and Storage

### 8.1 Raw and Processed Data

- `data/raw/`: scraped source documents
- `data/processed/`: cleaned chunks and extracted artifacts
- `data/embeddings/`: embedding outputs
- `data/reports/`: generated reports

### 8.2 Product JSON Files

The repository includes readable product information under [general_information/product_json/](general_information/product_json/). These files back the general-information endpoint and are also used by product-specific loaders.

## 9. Testing

### 9.1 Test Structure

- [tests/](tests/): automated unit and integration tests
- [scripts/test_quote_endpoints.py](scripts/test_quote_endpoints.py)
- [scripts/test_chatbot_api.py](scripts/test_chatbot_api.py)

### 9.2 Running Tests

```bash
source .venv/bin/activate
python -m pytest -q
```

Pytest is configured in [pyproject.toml](pyproject.toml) with async auto mode and coverage reporting.

### 9.3 Focus Areas

- flow validation
- product matching
- underwriting and premium calculations
- general-information endpoint behavior
- quote generation and downloads

## 10. Deployment

### 10.1 Docker

The Dockerfile starts by running database migrations and then launches the FastAPI app.

### 10.2 CI

The CI workflow is in [.github/workflows/ci.yml](.github/workflows/ci.yml). It installs dependencies, runs linting, and executes the test suite with coverage.

### 10.3 Hosting

Deployment targets include process-file-based platforms such as Railway and Heroku-compatible environments.

## 11. Operational Notes

- API keys protect the API by default.
- Real vs mock integrations are selected centrally.
- Conversation state can run on in-memory storage or Postgres depending on environment.
- Quote PDFs are stored on disk by default under `data/processed/quote_downloads/`.
- Product matching uses synonym expansion and fuzzy matching to handle common query variants.
- Several flows have reusable validation helpers that can be called by both APIs and guided forms.

## 12. Maintenance Guidance

When extending the system:

- Prefer adding new functionality in the relevant layer rather than in the main API file.
- Keep validation logic pure and reusable.
- Add tests alongside flow or API changes.
- Use mock clients for isolated testing when external systems are not available.
- Update product JSON rather than hardcoding product copy where possible.

## 13. Quick Start Summary

```bash
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

For full pipeline execution, see [README.md](README.md) and [SCRAPER_USAGE.md](SCRAPER_USAGE.md).
