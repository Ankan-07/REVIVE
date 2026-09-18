# syntax=docker/dockerfile:1
# ── Stage 1: dependency installer ───────────────────────────────────────────
FROM python:3.13-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy only dependency manifests first for layer caching
COPY backend/pyproject.toml backend/uv.lock ./

# Install production deps into a venv under /app/.venv
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
RUN uv sync --frozen --no-dev --no-install-project

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

# Non-root user for least-privilege runtime
RUN groupadd -r revive && useradd -r -g revive revive

WORKDIR /app

# Copy application source first
COPY backend/ ./

# Copy the pre-built venv from builder
COPY --from=builder /app/.venv /app/.venv

RUN chown -R revive:revive /app

# Make venv binaries available without activating
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Healthcheck — Docker marks container healthy before routing traffic
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz')" || exit 1

USER revive

EXPOSE 8000

# Entrypoint: migrate then serve.
CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"]
