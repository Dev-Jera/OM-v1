from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


_DOCKER_INTERNAL_HOSTS = {"postgres", "redis", "qdrant"}
_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


def _running_in_container() -> bool:
    if _is_truthy(os.getenv("RUNNING_IN_DOCKER")):
        return True
    return Path("/.dockerenv").exists()


def _parsed_hostname(url: str | None) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        return (urlparse(raw).hostname or "").strip().lower()
    except Exception:
        return ""


def _is_docker_internal_hostname(hostname: str) -> bool:
    return hostname in _DOCKER_INTERNAL_HOSTS


def should_use_real_postgres() -> bool:
    database_url = os.getenv("DATABASE_URL")
    enabled = _is_truthy(os.getenv("USE_POSTGRES_CONVERSATIONS"))
    if not database_url or not enabled:
        return False

    hostname = _parsed_hostname(database_url)
    if _is_docker_internal_hostname(hostname) and not _running_in_container():
        return False

    return True


def should_use_real_redis() -> bool:
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return False

    hostname = _parsed_hostname(redis_url)
    if _is_docker_internal_hostname(hostname) and not _running_in_container():
        return False

    return True


def runtime_service_summary() -> dict[str, str | bool]:
    database_url = os.getenv("DATABASE_URL", "")
    redis_url = os.getenv("REDIS_URL", "")
    return {
        "database_host": _parsed_hostname(database_url),
        "redis_host": _parsed_hostname(redis_url),
        "running_in_container": _running_in_container(),
        "use_real_postgres": should_use_real_postgres(),
        "use_real_redis": should_use_real_redis(),
    }
