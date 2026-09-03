"""Tool result contract, auth stub, parameter validation, and idempotency helpers.

PRD §17, §18, §38, §39  ·  BUILDPLAN Phase 5 Task 5.1

Every simulated action tool returns a :class:`ToolResult` — a uniform, JSON-serializable
envelope so the graph never has to guess whether an action worked.  Following §39, a result
distinguishes:

* ``success``          — did the action achieve its effect?
* ``error_code``       — machine-readable failure reason, if any.
* ``retryable``        — is it worth trying a *different* action, or is this terminal?
* ``failure_category`` — structured classification (§39) so the agent/router can reason
                         about *why* a failure occurred without pattern-matching strings.

Auth stub (§18):
:func:`require_system_context` must be called at the top of every action tool.  It accepts
only ``"system"`` (the LangGraph agent) or ``"operator"`` (human escalation handler).  Any
other caller is rejected before the DB is touched, and the call is logged as a
``TOOL_AUTH_FAILURE`` audit event.

Parameter validation (§18):
:func:`validate_tool_params` checks every ID and numeric parameter before any DB access.
Violations are rejected with ``error_code="PARAM_VALIDATION_FAILURE"``.

Idempotency (§38):
:func:`idempotency_key` builds the canonical ``case_id:action:attempt`` key shared by every
tool so a duplicate call returns the prior result instead of re-charging.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Allowed callers (§18 auth stub)
# ---------------------------------------------------------------------------
_ALLOWED_CALLERS = {"system", "operator"}

# ---------------------------------------------------------------------------
# ID format patterns (§18 parameter validation)
# ---------------------------------------------------------------------------
_CASE_ID_RE = re.compile(r"^RR-\d{5}$")
_PAY_ID_RE = re.compile(r"^PAY-\d{5}$")
_CHK_ID_RE = re.compile(r"^CHK-\d{5}$")
_INV_ID_RE = re.compile(r"^INV-\d{5}$")

# Canonical PREFIX-NNNNN format per entity kind, used by :func:`validate_entity_id`.
_ID_PATTERNS: Dict[str, Any] = {
    "PAY": _PAY_ID_RE,
    "CHK": _CHK_ID_RE,
    "INV": _INV_ID_RE,
}


# ---------------------------------------------------------------------------
# Failure classification (§39)
# ---------------------------------------------------------------------------
class FailureCategory(str, Enum):
    """Structured reason for a tool failure (PRD §39).

    Enables the router / observe_outcome node to distinguish recoverable infrastructure
    problems from terminal user-side or policy issues without inspecting raw error strings.
    """

    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    """Wrong caller context — tool not called via the agent or operator. Never retryable."""

    PARAM_VALIDATION_FAILURE = "PARAM_VALIDATION_FAILURE"
    """Malformed or out-of-range input parameter. Never retryable (fix the caller)."""

    RETRYABLE_SYSTEM_FAILURE = "RETRYABLE_SYSTEM_FAILURE"
    """Transient infrastructure problem (e.g. gateway timeout). Worth trying another action."""

    NON_RETRYABLE_USER_FAILURE = "NON_RETRYABLE_USER_FAILURE"
    """Terminal user-side issue (e.g. expired card, insufficient funds). Do not retry same method."""

    CUSTOMER_SIDE_FAILURE = "CUSTOMER_SIDE_FAILURE"
    """Customer action required (dispute, block). Automation cannot resolve; consider escalation."""

    POLICY_FAILURE = "POLICY_FAILURE"
    """Action was rejected by the policy engine before execution. Not a tool runtime error."""


# Map from the payment simulator's ``error_code`` strings to failure categories.
# Any code not in this map that indicates a failed payment defaults to RETRYABLE_SYSTEM_FAILURE.
_ERROR_CODE_CATEGORY: Dict[str, FailureCategory] = {
    "timeout":            FailureCategory.RETRYABLE_SYSTEM_FAILURE,
    "insufficient_funds": FailureCategory.NON_RETRYABLE_USER_FAILURE,
    "expired_card":       FailureCategory.NON_RETRYABLE_USER_FAILURE,
    "dispute":            FailureCategory.CUSTOMER_SIDE_FAILURE,
    "card_blocked":       FailureCategory.CUSTOMER_SIDE_FAILURE,
    "PAYMENT_NOT_FOUND":  FailureCategory.PARAM_VALIDATION_FAILURE,
}


def classify_error(error_code: Optional[str]) -> Optional[FailureCategory]:
    """Return the :class:`FailureCategory` for a given ``error_code``, or ``None`` on success."""
    if error_code is None:
        return None
    return _ERROR_CODE_CATEGORY.get(error_code, FailureCategory.RETRYABLE_SYSTEM_FAILURE)


# ---------------------------------------------------------------------------
# ToolResult envelope
# ---------------------------------------------------------------------------
class ToolResult(BaseModel):
    """Uniform outcome envelope returned by every action tool (PRD §39)."""

    tool: str
    success: bool
    error_code: Optional[str] = None
    retryable: bool = True
    detail: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)
    failure_category: Optional[FailureCategory] = None
    """Structured failure classification (§39). ``None`` on success."""


# ---------------------------------------------------------------------------
# Auth stub (§18)
# ---------------------------------------------------------------------------
class AuthorizationError(RuntimeError):
    """Raised when a tool is invoked by an unrecognised caller."""


def require_system_context(caller: str) -> None:
    """Assert that ``caller`` is a recognised, authorised invoker (§18 auth stub).

    Permitted values: ``"system"`` (LangGraph agent) and ``"operator"`` (human escalation).
    Anything else raises :class:`AuthorizationError`, which the tool must catch and convert
    into a terminal :class:`ToolResult` with ``error_code="AUTH_FAILURE"``.

    This is intentionally a *stub*: in a production deployment this would verify a signed
    JWT or service-account context.  For the simulation it enforces the calling convention so
    tests can prove the safety boundary exists.
    """
    if caller not in _ALLOWED_CALLERS:
        raise AuthorizationError(
            f"Tool invoked by unrecognised caller '{caller}'. "
            f"Permitted: {sorted(_ALLOWED_CALLERS)}."
        )


# ---------------------------------------------------------------------------
# Parameter validation (§18)
# ---------------------------------------------------------------------------
class ValidationError(ValueError):
    """Raised when a required tool parameter fails format or range checks."""


def validate_tool_params(
    *,
    case_id: str,
    payment_id: Optional[str] = None,
    attempt: Optional[int] = None,
    amount_at_risk: Optional[float] = None,
) -> None:
    """Validate ID formats and numeric ranges before any DB access (§18).

    ``case_id`` must match the canonical ``RR-NNNNN`` format generated by
    :func:`~app.domain.ids.generate_id`.  Within the LangGraph execution path
    this is guaranteed because :func:`~app.agent.nodes.execute_tool.execute_tool`
    reads ``case_id`` from ``config["configurable"]["thread_id"]``, which the
    LangSmith ``@traceable`` decorator cannot overwrite (it only mutates
    positional dict arguments, never ``config``).

    Raises :class:`ValidationError` with a descriptive message on the first
    failing check.  Callers should catch this and return a terminal
    :class:`ToolResult` immediately.
    """
    if not _CASE_ID_RE.match(case_id):
        raise ValidationError(
            f"case_id '{case_id}' does not match required format RR-NNNNN."
        )
    if payment_id is not None and not _PAY_ID_RE.match(payment_id):
        raise ValidationError(
            f"payment_id '{payment_id}' does not match required format PAY-NNNNN."
        )
    if attempt is not None and attempt < 1:
        raise ValidationError(
            f"attempt must be a positive integer, got {attempt}."
        )
    if amount_at_risk is not None and amount_at_risk <= 0:
        raise ValidationError(
            f"amount_at_risk must be > 0, got {amount_at_risk}."
        )


def validate_entity_id(entity_id: str, prefix: str) -> None:
    """Validate an entity id (payment/checkout/invoice) against its PREFIX-NNNNN format (§18).

    Unknown prefixes are accepted without a format check (nothing to enforce).
    """
    pattern = _ID_PATTERNS.get(prefix)
    if pattern is not None and not pattern.match(entity_id):
        raise ValidationError(
            f"entity_id '{entity_id}' does not match required format {prefix}-NNNNN."
        )


# ---------------------------------------------------------------------------
# Idempotency key (§38)
# ---------------------------------------------------------------------------
def idempotency_key(case_id: str, action: str, attempt: int) -> str:
    """The §38 idempotency key: ``case_id:action:attempt``."""
    return f"{case_id}:{action}:{attempt}"
