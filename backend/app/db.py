from datetime import datetime, timezone
from typing import Any, Generator
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.config import settings


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


def normalize_db_url(raw_url: str) -> str:
    """Ensure PostgreSQL connection strings use the psycopg v3 driver prefix and strip invalid libpq options."""
    if not raw_url:
        return raw_url
    if raw_url.startswith("postgresql://"):
        raw_url = "postgresql+psycopg://" + raw_url[len("postgresql://"):]
    elif raw_url.startswith("postgres://"):
        raw_url = "postgresql+psycopg://" + raw_url[len("postgres://"):]

    if "pgbouncer=" in raw_url:
        parsed = urlsplit(raw_url)
        query_params = parse_qsl(parsed.query)
        filtered_params = [(k, v) for k, v in query_params if k.lower() != "pgbouncer"]
        raw_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(filtered_params), parsed.fragment))

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
    # Disable psycopg prepared statements so PgBouncer / Supavisor transaction pooling works without collision
    connect_args["prepare_threshold"] = None
    engine_kwargs["connect_args"] = connect_args

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
