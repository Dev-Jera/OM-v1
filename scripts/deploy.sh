#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not installed or not on PATH" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is not installed or not on PATH" >&2
  exit 1
fi

if [[ ! -f "docker-compose.yml" ]]; then
  echo "docker-compose.yml not found. Run this script from the repository root." >&2
  exit 1
fi

if [[ ! -f ".env" ]]; then
  echo ".env not found. Create it before deploying." >&2
  exit 1
fi

echo "Starting data services (redis, postgres, qdrant)..."
docker compose up -d redis postgres qdrant

echo "Building API image..."
docker compose build api

echo "Running Alembic migrations..."
docker compose run --rm api alembic upgrade head

echo "Building and starting API..."
docker compose up -d --force-recreate api

echo "Waiting for API health check..."
for i in {1..30}; do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    echo "API is healthy."
    break
  fi
  if [[ "$i" -eq 30 ]]; then
    echo "API failed health check after deployment." >&2
    docker compose logs --tail=200 api
    exit 1
  fi
  sleep 2
done

echo "Deployment complete. Current service status:"
docker compose ps
