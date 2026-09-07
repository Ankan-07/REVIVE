from datetime import datetime, timezone
from typing import Any, Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import settings


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)

def normalize_db_url(raw_url: str) -> str:
    """Ensure PostgreSQL connection strings use the psycopg v3 driver prefix."""
    if not raw_url:
        return raw_url
    if raw_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw_url[len("postgresql://"):]
    if raw_url.startswith("postgres://"):
        return "postgresql+psycopg://" + raw_url[len("postgres://"):]
    return raw_url


engine_kwargs: dict[str, Any] = {"echo": False}
connect_args: dict[str, Any] = {}
effective_db_url = normalize_db_url(settings.database_url)

if effective_db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    engine_kwargs["connect_args"] = connect_args
elif effective_db_url.startswith("postgresql"):
    # Postgres / Supabase connection pooling (A1.1, A1.5)
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20

engine = create_engine(effective_db_url, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session_factory():
    """FastAPI dependency returning the *factory* (not a session).

    The agent runner needs to open its own short-lived sessions inside the graph nodes rather than
    borrow the request session, so the run-agent endpoint injects this instead of ``get_db``. Tests
    override it to point at their in-memory engine.
    """
    return SessionLocal
