from __future__ import annotations

from typing import Callable, Dict

from sqlalchemy.orm import Session

from app.agent.costs import cost_of
from app.audit import recorder
from app.models.invoice import Invoice
from app.schemas.enums import InterventionType
from app.services import intervention_service
from app.simulation import invoice_sim
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


def _run_invoice_action(
    db: Session,
    *,
    case_id: str,
    invoice_id: str,
    action: str,
    attempt: int,
    caller: str,
) -> ToolResult:
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

    try:
        validate_tool_params(case_id=case_id, attempt=attempt)
    except ValidationError as exc:
        return ToolResult(
            tool=action,
            success=False,
            error_code="PARAM_VALIDATION_FAILURE",
            retryable=False,
            detail=str(exc),
            failure_category=FailureCategory.PARAM_VALIDATION_FAILURE,
        )

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
    )

    try:
        sim = invoice_sim.simulate_invoice_action(db, invoice_id, action, attempt)
    except invoice_sim.InvoiceNotFoundError:
        return ToolResult(
            tool=action,
            success=False,
            error_code="INVOICE_NOT_FOUND",
            retryable=False,
            detail=f"invoice {invoice_id} not found",
            failure_category=FailureCategory.PARAM_VALIDATION_FAILURE,
        )

    intervention_service.create_executed(
        db, case_id=case_id, action=action, cost=cost_of(action), idempotency_key=key, result=sim
    )

    success = bool(sim["success"])
    return ToolResult(
        tool=action,
        success=success,
        error_code=None if success else "INVOICE_ACTION_FAILED",
        retryable=not success,
        detail=f"p={sim['probability']} (roll={sim['recovery_roll']})",
        data=sim,
        failure_category=FailureCategory.NON_RETRYABLE_USER_FAILURE if not success else None,
    )


def send_invoice_reminder(
    db: Session,
    *,
    case_id: str,
    invoice_id: str,
    attempt: int,
    caller: str = "system",
) -> ToolResult:
    return _run_invoice_action(
        db,
        case_id=case_id,
        invoice_id=invoice_id,
        action=InterventionType.SEND_REMINDER.value,
        attempt=attempt,
        caller=caller,
    )


def verify_promise(
    db: Session,
    *,
    case_id: str,
    invoice_id: str,
    attempt: int,
    caller: str = "system",
) -> ToolResult:
    return _run_invoice_action(
        db,
        case_id=case_id,
        invoice_id=invoice_id,
        action=InterventionType.VERIFY_PROMISE.value,
        attempt=attempt,
        caller=caller,
    )

TOOL_FOR_ACTION: Dict[str, Callable[..., ToolResult]] = {
    InterventionType.SEND_REMINDER.value: send_invoice_reminder,
    InterventionType.VERIFY_PROMISE.value: verify_promise,
}
