from __future__ import annotations

from typing import Callable, Dict

from sqlalchemy.orm import Session

from app.agent.costs import cost_of
from app.audit import recorder
from app.models.checkout import Checkout
from app.schemas.enums import InterventionType
from app.services import intervention_service
from app.simulation import checkout_sim
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


def _run_checkout_action(
    db: Session,
    *,
    case_id: str,
    checkout_id: str,
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
        sim = checkout_sim.simulate_checkout_action(db, checkout_id, action, attempt)
    except checkout_sim.CheckoutNotFoundError:
        return ToolResult(
            tool=action,
            success=False,
            error_code="CHECKOUT_NOT_FOUND",
            retryable=False,
            detail=f"checkout {checkout_id} not found",
            failure_category=FailureCategory.PARAM_VALIDATION_FAILURE,
        )

    intervention_service.create_executed(
        db, case_id=case_id, action=action, cost=cost_of(action), idempotency_key=key, result=sim
    )

    success = bool(sim["success"])
    return ToolResult(
        tool=action,
        success=success,
        error_code=None if success else "CHECKOUT_ACTION_FAILED",
        retryable=not success,
        detail=f"p={sim['probability']} (roll={sim['recovery_roll']})",
        data=sim,
        failure_category=FailureCategory.NON_RETRYABLE_USER_FAILURE if not success else None,
    )


def send_discount_message(
    db: Session,
    *,
    case_id: str,
    checkout_id: str,
    attempt: int,
    caller: str = "system",
) -> ToolResult:
    return _run_checkout_action(
        db,
        case_id=case_id,
        checkout_id=checkout_id,
        action=InterventionType.SEND_DISCOUNT_MESSAGE.value,
        attempt=attempt,
        caller=caller,
    )


def send_checkout_reminder(
    db: Session,
    *,
    case_id: str,
    checkout_id: str,
    attempt: int,
    caller: str = "system",
) -> ToolResult:
    return _run_checkout_action(
        db,
        case_id=case_id,
        checkout_id=checkout_id,
        action=InterventionType.SEND_REMINDER.value,
        attempt=attempt,
        caller=caller,
    )

TOOL_FOR_ACTION: Dict[str, Callable[..., ToolResult]] = {
    InterventionType.SEND_DISCOUNT_MESSAGE.value: send_discount_message,
    InterventionType.SEND_REMINDER.value: send_checkout_reminder,
}
