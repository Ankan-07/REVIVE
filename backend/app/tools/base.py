"""Tool result contract and idempotency helpers (PRD §38, §39).

Every simulated action tool returns a :class:`ToolResult` — a uniform, JSON-serializable envelope so
the graph never has to guess whether an action worked. Following §39, a result distinguishes:

* ``success``   — did the action achieve its effect (e.g. did the payment recover)?
* ``error_code``— machine-readable failure reason, if any.
* ``retryable`` — is it worth trying a *different* action, or is this terminal for the case?

Idempotency (§38) is keyed on ``case_id:action:attempt``: replaying the same key must return the
prior result and must not create a second side effect. The key is built here so every tool agrees on
the format.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Uniform outcome envelope returned by every action tool (PRD §39)."""

    tool: str
    success: bool
    error_code: Optional[str] = None
    retryable: bool = True
    detail: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)


def idempotency_key(case_id: str, action: str, attempt: int) -> str:
    """The §38 idempotency key: ``case_id:action:attempt``."""
    return f"{case_id}:{action}:{attempt}"
