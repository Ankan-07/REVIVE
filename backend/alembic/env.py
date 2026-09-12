import sys
from logging.config import fileConfig
from pathlib import Path

# Ensure backend root is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.db import Base, normalize_db_url
import app.models  # Ensure all ORM models are registered for autogenerate

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata


def _get_migration_url() -> str:
    """Prefer direct connection (SUPABASE_DB_URL) for migrations, fallback to DATABASE_URL (A1.5)."""
    import os
    import socket
    from urllib.parse import urlsplit

    alembic_url = os.getenv("ALEMBIC_DB_URL")
    if alembic_url:
        return normalize_db_url(alembic_url)

    if settings.supabase_db_url:
        try:
            parsed = urlsplit(settings.supabase_db_url)
            host = parsed.hostname
            if host:
                socket.getaddrinfo(host, parsed.port or 5432)
                return normalize_db_url(settings.supabase_db_url)
        except Exception:
            # Fallback to database_url if direct Supabase host is unresolvable on current network
            pass

    return normalize_db_url(settings.database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = _get_migration_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_migration_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
