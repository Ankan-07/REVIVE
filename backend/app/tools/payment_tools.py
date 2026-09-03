"""Simulated payment-recovery tools (PRD §17, §18, §28, §38, §39).

Each tool is a thin declaration over :func:`app.tools.runner.run_action_tool`, which owns the shared
pipeline: §18 auth + parameter validation, §38 idempotent replay, pre-execution audit,
§28 deterministic simulation, and Intervention persistence.  The only payment-specific parts are the
oracle (:mod:`app.simulation.payment_sim`), the ``PAY-NNNNN`` entity-id format, and how a failed
outcome is classified — from the error code stored on the ``Payment`` row, mapped through §39.

These are the only places where \"side effects\" (intervention rows) are written.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.schemas.enums import InterventionType, PaymentStatus
from app.simulation import payment_sim
from app.tools import runner
from app.tools.base import (
    AuthorizationError,
    FailureCategory,
    ToolResult,
    ValidationError,
    classify_error,
    require_system_context,
    validate_tool_params,
)


# ---------------------------------------------------------------------------
# Payment-domain outcome classification (§39)
# ---------------------------------------------------------------------------
def _payment_error_code_of(db: Session, sim: dict) -> Optional[str]:
    """Failed payments report the error_code stored on the Payment row, not the sim result dict."""
    row = db.query(Payment).filter(Payment.id == sim["payment_id"]).first()
    return row.error_code if row else None


def _payment_category_of(db: Session, sim: dict, error_code: Optional[str]) -> Optional[FailureCategory]:
    return classify_error(error_code) if error_code else None


def _payment_retryable_when_failed(db: Session, sim: dict, error_code: Optional[str]) -> bool:
    return classify_error(error_code) == FailureCategory.RETRYABLE_SYSTEM_FAILURE


def _payment_summary(sim: dict) -> str:
    return f"p={sim['probability']} via {sim['gateway_used']} (roll={sim['recovery_roll']})"


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
    """Run a payment-attempt tool through the shared §18/§38/§39 pipeline."""
    return runner.run_action_tool(
        db,
        case_id=case_id,
        entity_id=payment_id,
        action=action,
        attempt=attempt,
        caller=caller,
        entity_prefix="PAY",
        simulate=payment_sim.simulate_payment,
        not_found_exception=payment_sim.PaymentNotFoundError,
        not_found_code="PAYMENT_NOT_FOUND",
        entity_label="payment",
        summary=_payment_summary,
        error_code_of=_payment_error_code_of,
        category_of=_payment_category_of,
        retryable_when_failed=_payment_retryable_when_failed,
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
