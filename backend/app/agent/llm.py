"""LLM access for the agent's reasoning nodes (PRD §14, §15, §31, §56).

Two responsibilities:

1. Hand out a **traced** OpenAI client (``wrap_openai`` -> every call shows up in LangSmith).
2. :func:`structured_complete` — call the model, validate the JSON against a Pydantic contract, and
   **retry once** with a corrective message on invalid output (PRD §56 "schema validates" step).

If ``OPENAI_API_KEY`` is absent, :func:`get_client` returns ``None`` and
:func:`structured_complete` raises :class:`LLMUnavailable`. Reasoning nodes catch that and fall
back to a deterministic heuristic that returns the *same* contract, so the whole graph — and the
test suite — runs fully offline while remaining honest about what produced each value.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, List, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.observability import configure_tracing, traceable

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """No OpenAI key configured — caller should use its deterministic fallback."""


class LLMUnavailableInProduction(RuntimeError):
    """Loud 503 error when LLM is unavailable in production (Phase E2)."""
    status_code: int = 503


class LLMValidationError(ValueError):
    """The model never produced schema-valid JSON, even after the corrective retry."""


@lru_cache(maxsize=1)
def get_client():
    """A LangSmith-traced OpenAI client, or ``None`` when no API key is set.

    ``openai``/``langsmith.wrappers`` are imported lazily so importing this module never hard-depends
    on them, and tracing config is applied first so the wrapped client emits into the right project.
    """
    configure_tracing()
    if not os.getenv("OPENAI_API_KEY"):
        return None
    from langsmith.wrappers import wrap_openai
    from openai import OpenAI

    kwargs: dict[str, Any] = {}
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return wrap_openai(OpenAI(**kwargs))


def is_llm_available() -> bool:
    return get_client() is not None


@traceable(name="llm.structured_complete", run_type="chain")
def structured_complete(
    schema: Type[T],
    *,
    system: str = "",
    user: str = "",
    model: str = "gpt-4o-mini",
    system_prompt: Optional[str] = None,
    user_prompt: Optional[str] = None,
    client: Any = None,
    max_retries: int = 1,
) -> T:
    """Call the model and return an instance of ``schema``, retrying on invalid JSON.

    ``client`` is injectable purely for testing; production passes ``None`` and uses
    :func:`get_client`. Requests ``response_format=json_object`` and validates the content with
    Pydantic; on failure it feeds the error back to the model and tries again (PRD §31/§56).
    """
    system = system or system_prompt or ""
    user = user or user_prompt or ""

    from app.config import settings
    if settings.app_env.lower() == "prod" and (client is None and not is_llm_available()):
        raise LLMUnavailableInProduction(
            "[E2 Quarantine] LLM client is unavailable in production (APP_ENV=prod). "
            "Silent heuristic fallbacks are strictly forbidden on the live path."
        )

    client = client or get_client()
    if client is None:
        raise LLMUnavailable("OPENAI_API_KEY is not set")

    messages: List[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    last_error: Optional[Exception] = None
    for _ in range(max_retries + 1):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or ""
        try:
            return schema.model_validate_json(content)
        except (ValidationError, ValueError) as exc:
            last_error = exc
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Your previous response was invalid: {exc}. "
                        "Respond with ONLY valid JSON that matches the required schema."
                    ),
                }
            )

    raise LLMValidationError(
        f"Model did not return schema-valid JSON after {max_retries + 1} attempts: {last_error}"
    )
