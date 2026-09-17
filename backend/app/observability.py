"""LangSmith tracing for the Revenue Rescue Engine (PRD §42, BUILDPLAN §7).

This is the single place that turns LangSmith tracing on for the whole backend.
Call :func:`configure_tracing` once at process start (FastAPI startup, the agent
entrypoint, a script, a test fixture) and every downstream LangChain/LangGraph
call is traced automatically.

Two tracing paths, both flowing to the same LangSmith project:

* **LangChain / LangGraph** — automatic. Once ``LANGSMITH_TRACING=true`` and
  ``LANGSMITH_API_KEY`` are set, the diagnose/plan LLM nodes and the graph
  itself emit traces with no extra code.
* **Plain Python / direct OpenAI** — use :data:`traceable` to wrap a function
  and :func:`traced_openai_client` to wrap the OpenAI client, so deterministic
  nodes (context builder, EV scoring, policy check) show up in the same trace
  tree as the LLM calls.

Nothing here makes financial decisions — it only records what happened, which is
exactly the auditability/observability the PRD asks for.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
import re

from dotenv import load_dotenv
from langsmith import traceable  # re-exported for convenient `from app.observability import traceable`

__all__ = [
    "configure_tracing",
    "traceable",
    "traced_openai_client",
    "is_tracing_enabled",
    "tracing_project",
    "DEFAULT_PROJECT",
    "mask_pii",
]

# backend/app/observability.py -> parents[0]=app, [1]=backend, [2]=repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_PROJECT = "revenue-rescue-engine"

_TRUTHY = {"1", "true", "yes", "on"}


def _load_env() -> None:
    """Load .env from the repo root, then fall back to cwd / real environment.

    ``load_dotenv`` never overrides variables already present in the real
    environment, so a value exported in the shell always wins.
    """
    load_dotenv(_REPO_ROOT / ".env")
    load_dotenv()


# Populate os.environ from the repo .env at import time. Without this, env-var readers such as
# razorpay_service.is_configured() only ever saw what the shell exported (pydantic Settings loads
# the file into its own fields, but does not set os.environ), so checkout returned 503 even with
# keys present in .env. Loading here covers every entry point that imports observability -- which
# main.py does first, and which every traceable service pulls in transitively.
_load_env()


@lru_cache(maxsize=1)
def configure_tracing() -> bool:
    """Enable LangSmith tracing if an API key is available. Idempotent.

    Returns ``True`` when tracing ends up enabled. Never raises: with no API key
    the app simply runs untraced (PRD §55 — degrade gracefully, never crash a
    recovery run because observability is misconfigured).
    """
    _load_env()

    api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    if not api_key:
        os.environ["LANGSMITH_TRACING"] = "false"
        return False

    # Respect an explicit opt-out (LANGSMITH_TRACING / legacy LANGCHAIN_TRACING_V2);
    # otherwise default tracing ON since a key is present.
    flag = os.getenv("LANGSMITH_TRACING", os.getenv("LANGCHAIN_TRACING_V2", "true"))
    enabled = str(flag).strip().lower() in _TRUTHY

    os.environ["LANGSMITH_TRACING"] = "true" if enabled else "false"
    os.environ.setdefault("LANGSMITH_API_KEY", api_key)
    os.environ.setdefault("LANGSMITH_PROJECT", DEFAULT_PROJECT)
    return enabled


def is_tracing_enabled() -> bool:
    """Whether tracing is currently switched on in the environment."""
    return os.getenv("LANGSMITH_TRACING", "false").strip().lower() == "true"


def tracing_project() -> str:
    """The LangSmith project traces are grouped under."""
    return os.getenv("LANGSMITH_PROJECT", DEFAULT_PROJECT)


def traced_openai_client():
    """Return an OpenAI client whose calls are auto-traced to LangSmith.

    ``openai`` is imported lazily so importing this module never hard-depends on
    it. Raises ``RuntimeError`` if ``OPENAI_API_KEY`` is missing.
    """
    configure_tracing()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set — cannot create a traced OpenAI client. "
            "Add it to .env (see .env.example)."
        )
    from langsmith.wrappers import wrap_openai
    from openai import OpenAI

    return wrap_openai(OpenAI())


def mask_pii(text: str) -> str:
    """Mask email addresses and phone numbers in text before trace/log emission (Phase C3)."""
    if not text or not isinstance(text, str):
        return text

    # Mask email: user part masked as u***@domain.com
    email_pattern = r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"
    masked = re.sub(email_pattern, r"\1***@\2", text)

    # Mask phone: digits masked as +91*****3210
    phone_pattern = r"(\+?\d{2,3})?\s*(\d{2})\d{4,6}(\d{4})"
    masked = re.sub(phone_pattern, r"\1*****\3", masked)

    return masked

