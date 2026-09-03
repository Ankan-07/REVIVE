"""Shared action-tool execution pipeline (PRD §17, §18, §28, §38, §39).

The payment / checkout / invoice action tools all follow the same sequence — auth check (§18),
parameter validation (§18), idempotent replay (§38), pre-execution audit, deterministic simulation
(§28), and persistence of the Intervention row — and differ only in *which* simulator oracle they
call and how a failed outcome is classified (§39).  :func:`run_action_tool` owns that pipeline once;
each tool module stays a thin declaration of its simulator, not-found behavior, and failure
classification.

A freshly simulated outcome (plus its ``error_code`` / ``failure_category``) is stored in the
intervention's ``payload_json``, so replaying the same ``case_id:action:attempt`` key reproduces the
original classification instead of re-running the oracle.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Type

from sqlalchemy.orm import Session

from app.agent.costs import cost_of
from app.audit import recorder
from app.services import intervention_service
from app.tools.base import (
    AuthorizationError,
    FailureCategory,
    ToolResult,
    ValidationError,
    idempotency_key,
    require_system_context,
    validate_entity_id,
    validate_tool_params,
)


def _default_summary(sim: Dict[str, Any]) -> str:
    """Human-readable one-liner for the outcome (shared by every simulator's payload)."""
    return f"p={sim['probability']} (roll={sim['recovery_roll']})"


def _replay_result(action: str, payload: Dict[str, Any]) -> ToolResult:
    """Rebuild the ToolResult from a previously persisted intervention payload (§38)."""
    success = bool(payload.get("success"))
    category = payload.get("failure_category")
    return ToolResult(
        tool=action,
        success=success,
        error_code=payload.get("error_code"),
        retryable=not success,
        detail="idempotent replay of a prior attempt",
        data={k: v for k, v in payload.items()
              if k not in ("idempotency_key", "error_code", "failure_category")},
        failure_category=FailureCategory(category) if category else None,
    )


def run_action_tool(
    db: Session,
    *,
    case_id: str,
    entity_id: Optional[str],
    action: str,
    attempt: int,
    caller: str,
    simulate: Callable[[Session, str, str, int], Dict[str, Any]],
    not_found_exception: Type[Exception],
    not_found_code: str,
    entity_label: str,
    entity_prefix: Optional[str] = None,
    failure_code: Optional[str] = None,
    summary: Callable[[Dict[str, Any]], str] = _default_summary,
    error_code_of: Optional[Callable[[Session, Dict[str, Any]], Optional[str]]] = None,
    category_of: Optional[
        Callable[[Session, Dict[str, Any], Optional[str]], FailureCategory]
    ] = None,
    retryable_when_failed: Callable[
        [Session, Dict[str, Any], Optional[str]], bool
    ] = lambda db, sim, error_code: True,
) -> ToolResult:
    """Run one simulated action through the §18/§38/§39 pipeline.

    ``simulate(db, entity_id, action, attempt)`` is the deterministic, read-only oracle.

    Classification hooks describe what a *failed* outcome means in this tool's domain; on success the
    result always carries ``error_code=None``, ``failure_category=None``, ``retryable=False``.  The
    defaults model a generic user-side failure (non-retryable code ``failure_code``); the payment
    tools override them to read the stored ``Payment.error_code`` and pick the §39 category.
    """
    # ---- 1. Auth (§18): reject unknown callers before the DB is touched. -----------------------
    try:
        require_system_context(caller)
    except AuthorizationError as exc:
        return ToolResult(
            tool=action, success=False, error_code="AUTH_FAILURE", retryable=False,
            detail=str(exc), failure_category=FailureCategory.AUTHENTICATION_FAILURE,
        )

    # ---- 2. Parameter validation (§18) ----------------------------------------------------------
    try:
        validate_tool_params(case_id=case_id, attempt=attempt)
        if entity_prefix and entity_id is not None:
            validate_entity_id(entity_id, entity_prefix)
    except ValidationError as exc:
        return ToolResult(
            tool=action, success=False, error_code="PARAM_VALIDATION_FAILURE", retryable=False,
            detail=str(exc), failure_category=FailureCategory.PARAM_VALIDATION_FAILURE,
        )

    # ---- 3. Idempotency (§38): a replay returns the prior result, no second side effect ---------
    key = idempotency_key(case_id, action, attempt)
    existing = intervention_service.get_by_idempotency_key(db, case_id, key)
    if existing is not None:
        return _replay_result(action, existing.payload_json or {})

    # ---- 4. Pre-execution audit: proves the safety layer ran before any simulation --------------
    recorder.record(
        db,
        case_id,
        "TOOL_VALIDATION_PASSED",
        payload={"action": action, "attempt": attempt, "caller": caller, "idempotency_key": key},
    )

    # ---- 5. Simulate (§28) — the deterministic oracle, resolved and persisted --------------------
    try:
        sim = simulate(db, entity_id, action, attempt)
    except not_found_exception:
        return ToolResult(
            tool=action, success=False, error_code=not_found_code, retryable=False,
            detail=f"{entity_label} {entity_id} not found",
            failure_category=FailureCategory.PARAM_VALIDATION_FAILURE,
        )

    success = bool(sim["success"])
    if success:
        error_code: Optional[str] = None
        category: Optional[FailureCategory] = None
        retryable = False
    else:
        error_code = error_code_of(db, sim) if error_code_of else failure_code
        category = (
            category_of(db, sim, error_code)
            if category_of
            else FailureCategory.NON_RETRYABLE_USER_FAILURE
        )
        retryable = retryable_when_failed(db, sim, error_code)

    intervention_service.create_executed(
        db, case_id=case_id, action=action, cost=cost_of(action), idempotency_key=key,
        result={**sim, "error_code": error_code,
                "failure_category": category.value if category else None},
    )

    return ToolResult(
        tool=action, success=success, error_code=error_code, retryable=retryable,
        detail=summary(sim), data=sim, failure_category=category,
    )
