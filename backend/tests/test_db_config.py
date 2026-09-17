"""Unit tests for database engine configuration and pooling (TDD)."""
import pytest
from app.db import normalize_db_url, connect_args, effective_db_url


def test_normalize_db_url_postgresql_prefix():
    assert normalize_db_url("postgresql://user:pass@host:5432/db") == "postgresql+psycopg://user:pass@host:5432/db"
    assert normalize_db_url("postgres://user:pass@host:5432/db") == "postgresql+psycopg://user:pass@host:5432/db"


def test_normalize_db_url_strips_pgbouncer():
    url = "postgresql://user:pass@host:6543/db?pgbouncer=true&sslmode=require"
    normalized = normalize_db_url(url)
    assert "pgbouncer=" not in normalized
    assert "sslmode=require" in normalized
    assert normalized.startswith("postgresql+psycopg://")


def test_postgres_engine_connect_args_disables_prepared_statements():
    """Verify that postgres configuration passes prepare_threshold=None to avoid PgBouncer collision."""
    if effective_db_url.startswith("postgresql"):
        assert "prepare_threshold" in connect_args and connect_args["prepare_threshold"] is None
