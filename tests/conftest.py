"""Pytest fixtures for underwriting and quotation tests."""

import pytest

from src.database.postgres import PostgresDB


@pytest.fixture
def db():
    """In-memory PostgresDB stub for tests."""
    return PostgresDB()
