"""Simulated payment-recovery tools (PRD §17, §18, §28, §38, §39).

Each tool wraps the deterministic :mod:`app.simulation.payment_sim` oracle with:

1. **Auth check** (§18): :func:`~app.tools.base.require_system_context` rejects any caller
   that is not ``"system"`` or ``"operator"`` before the DB is touched.
2. **Parameter validation** (§18): :func:`~app.tools.base.validate_tool_params` verifies ID
   formats and numeric constraints; failures are terminal, non-retryable.
3. **Pre-execution audit record**: ``TOOL_VALIDATION_PASSED`` is written immediately after
   both checks succeed, so the audit trail proves the safety boundary was enforced.
4. **Idempotency** (§38): keyed on ``case_id:action:attempt`` — replaying the same key returns
   the prior stored result and creates no second intervention row.
5. **Failure classification** (§39): the simulator's ``error_code`` is mapped to a
   :class:`~app.tools.base.FailureCategory` so the graph router can reason about *why* a
   failure occurred without string-matching.

These are the only places where "side effects" (intervention rows) are written.
"""
from __future__ import annotations

from typing import Callable, Dict

from sqlalchemy.orm import Session

from app.agent.costs import cost_of
from app.audit import recorder
from app.models.payment import Payment
from app.schemas.enums import InterventionType, PaymentStatus
from app.services import intervention_service
from app.simulation import payment_sim
from app.tools.base import (
    AuthorizationError,
    FailureCategory,
    ToolResult,
    ValidationError,
    classify_error,
    idempotency_key,
    require_system_context,
    validate_tool_params,
)


# ---------------------------------------------------------------------------
# Internal shared body
# ---------------------------------------------------------------------------
def _run_action(
    db: Session,
    *,
    case_id: str,
    payment_id: str,
    action: str,
    attempt: int,
    caller: str,
) -> ToolResult:
    """Shared body for the payment-attempt tools.

    Execution order (§18 rule: validate before touching the DB):

    1. Auth check  — reject unknown callers immediately.
    2. Param check — reject bad IDs / out-of-range numbers immediately.
    3. Idempotency — return the prior result if this key was already executed.
    4. Audit        — write TOOL_VALIDATION_PASSED (proves safety layer ran).
    5. Simulate     — call the deterministic oracle.
    6. Persist      — store the Intervention row and return ToolResult.
    """
    # ---- 1. Auth -------------------------------------------------------
    try:
        require_system_context(caller)
    except AuthorizationError as exc:
        return ToolResult(
            tool=action,
            success=False,
            error_code="AUTH_FAILURE",
            retryable=False,
            detail=str(exc),
            failure_category=FailureCategory.AUTHENTICATION_FAILURE,
        )

    # ---- 2. Parameter validation ----------------------------------------
    try:
        validate_tool_params(case_id=case_id, payment_id=payment_id, attempt=attempt)
    except ValidationError as exc:
        return ToolResult(
            tool=action,
            success=False,
            error_code="PARAM_VALIDATION_FAILURE",
            retryable=False,
            detail=str(exc),
            failure_category=FailureCategory.PARAM_VALIDATION_FAILURE,
        )

    # ---- 3. Idempotency -------------------------------------------------
    key = idempotency_key(case_id, action, attempt)
    existing = intervention_service.get_by_idempotency_key(db, case_id, key)
    if existing is not None:
        payload = existing.payload_json or {}
        success = bool(payload.get("success"))
        stored_code = payload.get("error_code")
        return ToolResult(
            tool=action,
            success=success,
            error_code=stored_code,
            retryable=not success,
            detail="idempotent replay of a prior attempt",
            data={k: v for k, v in payload.items() if k != "idempotency_key"},
            failure_category=classify_error(stored_code) if not success else None,
        )

    # ---- 4. Pre-execution audit (safety boundary proof) -----------------
    recorder.record(
        db,
        case_id,
        "TOOL_VALIDATION_PASSED",
        payload={
            "action": action,
            "attempt": attempt,
            "caller": caller,
            "idempotency_key": key,
        },
        # commit=True (default) so the audit row is durable before simulation runs.
        # Using True here also avoids any session-state issues on the StaticPool shared
        # connection used in integration tests.
    )

    # ---- 5. Simulate ----------------------------------------------------
    try:
        sim = payment_sim.simulate_payment(db, payment_id, action, attempt)
    except payment_sim.PaymentNotFoundError:
        return ToolResult(
            tool=action,
            success=False,
            error_code="PAYMENT_NOT_FOUND",
            retryable=False,
            detail=f"payment {payment_id} not found",
            failure_category=FailureCategory.PARAM_VALIDATION_FAILURE,
        )

    # ---- 6. Persist & return --------------------------------------------
    intervention_service.create_executed(
        db, case_id=case_id, action=action, cost=cost_of(action), idempotency_key=key, result=sim
    )

    success = bool(sim["success"])
    # Classify: on success there is no failure; on failure use the payment's stored error_code
    # (from the Payment row, not the sim dict which doesn't re-expose it) to pick the category.
    payment_row = db.query(Payment).filter(Payment.id == payment_id).first()
    payment_error_code = (payment_row.error_code if payment_row else None) if not success else None
    category = classify_error(payment_error_code) if not success else None

    return ToolResult(
        tool=action,
        success=success,
        error_code=payment_error_code if not success else None,
        retryable=not success and category == FailureCategory.RETRYABLE_SYSTEM_FAILURE,
        detail=f"p={sim['probability']} via {sim['gateway_used']} (roll={sim['recovery_roll']})",
        data=sim,
        failure_category=category,
    )


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------
def check_payment_status(db: Session, payment_id: str, *, caller: str = "system") -> ToolResult:
    """Read-only status probe for a payment (no side effect, PRD §17).

    Validates auth and the ``payment_id`` format before touching the DB.
    """
    try:
        require_system_context(caller)
    except AuthorizationError as exc:
        return ToolResult(
            tool="check_payment_status",
            success=False,
            error_code="AUTH_FAILURE",
            retryable=False,
            detail=str(exc),
            failure_category=FailureCategory.AUTHENTICATION_FAILURE,
        )
    try:
        validate_tool_params(case_id="RR-00000", payment_id=payment_id)  # case_id not meaningful here
    except ValidationError as exc:
        return ToolResult(
            tool="check_payment_status",
            success=False,
            error_code="PARAM_VALIDATION_FAILURE",
            retryable=False,
            detail=str(exc),
            failure_category=FailureCategory.PARAM_VALIDATION_FAILURE,
        )

    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment is None:
        return ToolResult(
            tool="check_payment_status",
            success=False,
            error_code="PAYMENT_NOT_FOUND",
            retryable=False,
            detail=f"payment {payment_id} not found",
            failure_category=FailureCategory.PARAM_VALIDATION_FAILURE,
        )
    return ToolResult(
        tool="check_payment_status",
        success=payment.status == PaymentStatus.SUCCEEDED.value,
        retryable=payment.status == PaymentStatus.FAILED.value,
        detail=f"status={payment.status}",
        data={"status": payment.status, "gateway": payment.gateway, "error_code": payment.error_code},
    )


def retry_payment(
    db: Session,
    *,
    case_id: str,
    payment_id: str,
    attempt: int,
    caller: str = "system",
) -> ToolResult:
    """Retry the payment on its current gateway (PRD §17)."""
    return _run_action(
        db,
        case_id=case_id,
        payment_id=payment_id,
        action=InterventionType.RETRY_PAYMENT.value,
        attempt=attempt,
        caller=caller,
    )


def switch_gateway(
    db: Session,
    *,
    case_id: str,
    payment_id: str,
    attempt: int,
    caller: str = "system",
) -> ToolResult:
    """Re-attempt the payment on the healthiest alternative gateway (PRD §17)."""
    return _run_action(
        db,
        case_id=case_id,
        payment_id=payment_id,
        action=InterventionType.SWITCH_GATEWAY.value,
        attempt=attempt,
        caller=caller,
    )


def create_payment_link(
    db: Session,
    *,
    case_id: str,
    payment_id: str,
    attempt: int,
    caller: str = "system",
) -> ToolResult:
    """Issue a hosted payment link so the customer can re-pay on a healthy instrument (PRD §17)."""
    return _run_action(
        db,
        case_id=case_id,
        payment_id=payment_id,
        action=InterventionType.CREATE_PAYMENT_LINK.value,
        attempt=attempt,
        caller=caller,
    )


# Dispatch table so the execute_tool node can select a tool from the chosen action string.
TOOL_FOR_ACTION: Dict[str, Callable[..., ToolResult]] = {
    InterventionType.RETRY_PAYMENT.value: retry_payment,
    InterventionType.SWITCH_GATEWAY.value: switch_gateway,
    InterventionType.CREATE_PAYMENT_LINK.value: create_payment_link,
}
