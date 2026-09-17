"""Live Razorpay payment-recovery tools (PRD §17, §18, §38, §40, Phase B2).

These tools execute real test-mode Razorpay actions:
- RETRY_PAYMENT: Creates a new Razorpay order for checkout modal payment re-attempt.
- CREATE_PAYMENT_LINK: Creates a real Razorpay payment link (with reminder_enable=False).

Never call simulation oracles or mutate money directly; state changes occur via verified
callbacks and webhooks (Phase B1).
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.agent.costs import cost_of
from app.models.intervention import Intervention
from app.schemas.enums import InterventionType
from app.services import case_service, intervention_service, razorpay_service
from app.tools.base import (
    AuthorizationError,
    FailureCategory,
    ToolResult,
    ValidationError,
    require_system_context,
    validate_tool_params,
)


def _replay_intervention(action: str, intervention: Intervention) -> ToolResult:
    """Return ToolResult from a previously recorded intervention (idempotency)."""
    payload = intervention.payload_json or {}
    success = bool(payload.get("success", True))
    return ToolResult(
        tool=action,
        success=success,
        detail="idempotent replay of prior live attempt",
        data={k: v for k, v in payload.items() if k not in ("idempotency_key",)},
        retryable=not success,
    )


def live_retry_payment(
    db: Session,
    *,
    case_id: str,
    attempt: int,
    caller: str = "system",
    payment_id: Optional[str] = None,
    **kwargs: Any,
) -> ToolResult:
    """Create a new Razorpay order for checkout modal re-attempt (Phase B2)."""
    try:
        require_system_context(caller)
        validate_tool_params(case_id=case_id, attempt=attempt)
    except (AuthorizationError, ValidationError) as exc:
        return ToolResult(
            tool=InterventionType.RETRY_PAYMENT.value,
            success=False,
            error_code="VALIDATION_ERROR",
            detail=str(exc),
            retryable=False,
        )

    # Idempotency check (§38)
    idemp_key = f"{case_id}:retry:{attempt}"
    existing = intervention_service.get_by_idempotency_key(db, case_id, idemp_key)
    if existing:
        return _replay_intervention(InterventionType.RETRY_PAYMENT.value, existing)

    case = case_service.get_case_row(db, case_id)
    target_payment_id = payment_id or (case.payment_id if case else None)
    if not target_payment_id:
        return ToolResult(
            tool=InterventionType.RETRY_PAYMENT.value,
            success=False,
            error_code="PAYMENT_NOT_FOUND",
            detail=f"No payment_id found for case {case_id}",
            retryable=False,
        )

    try:
        order_res = razorpay_service.create_order_for_payment(db, payment_id=target_payment_id)
    except Exception as exc:
        return ToolResult(
            tool=InterventionType.RETRY_PAYMENT.value,
            success=False,
            error_code="GATEWAY_ERROR",
            detail=f"Failed to create Razorpay order: {exc}",
            retryable=True,
            failure_category=FailureCategory.RETRYABLE_SYSTEM_FAILURE,
        )

    cost = cost_of(InterventionType.RETRY_PAYMENT.value)
    payload_data = {
        "success": True,
        "action": InterventionType.RETRY_PAYMENT.value,
        "attempt": attempt,
        "order_id": order_res["order_id"],
        "amount": order_res["amount"],
        "provider": "razorpay",
    }

    intervention_service.create_executed(
        db,
        case_id=case_id,
        action=InterventionType.RETRY_PAYMENT.value,
        cost=cost,
        idempotency_key=idemp_key,
        result=payload_data,
    )

    return ToolResult(
        tool=InterventionType.RETRY_PAYMENT.value,
        success=True,
        detail=f"Created Razorpay order {order_res['order_id']} for customer checkout modal payment",
        data=payload_data,
    )


def live_create_payment_link(
    db: Session,
    *,
    case_id: str,
    attempt: int,
    caller: str = "system",
    payment_id: Optional[str] = None,
    **kwargs: Any,
) -> ToolResult:
    """Create a real Razorpay payment link with native reminders disabled (Phase B2)."""
    try:
        require_system_context(caller)
        validate_tool_params(case_id=case_id, attempt=attempt)
    except (AuthorizationError, ValidationError) as exc:
        return ToolResult(
            tool=InterventionType.CREATE_PAYMENT_LINK.value,
            success=False,
            error_code="VALIDATION_ERROR",
            detail=str(exc),
            retryable=False,
        )

    # Idempotency check (§38)
    idemp_key = f"{case_id}:payment_link:{attempt}"
    existing = intervention_service.get_by_idempotency_key(db, case_id, idemp_key)
    if existing:
        return _replay_intervention(InterventionType.CREATE_PAYMENT_LINK.value, existing)

    try:
        link_res = razorpay_service.create_payment_link_for_case(db, case_id=case_id)
    except Exception as exc:
        return ToolResult(
            tool=InterventionType.CREATE_PAYMENT_LINK.value,
            success=False,
            error_code="GATEWAY_ERROR",
            detail=f"Failed to create Razorpay payment link: {exc}",
            retryable=True,
            failure_category=FailureCategory.RETRYABLE_SYSTEM_FAILURE,
        )

    cost = cost_of(InterventionType.CREATE_PAYMENT_LINK.value)
    payload_data = {
        "success": True,
        "action": InterventionType.CREATE_PAYMENT_LINK.value,
        "attempt": attempt,
        "payment_link_id": link_res.get("payment_link_id") or link_res.get("id", ""),
        "short_url": link_res.get("short_url", ""),
        "amount": link_res.get("amount", 0.0),
        "provider": "razorpay",
    }

    intervention_service.create_executed(
        db,
        case_id=case_id,
        action=InterventionType.CREATE_PAYMENT_LINK.value,
        cost=cost,
        idempotency_key=idemp_key,
        result=payload_data,
    )

    return ToolResult(
        tool=InterventionType.CREATE_PAYMENT_LINK.value,
        success=True,
        detail=f"Created Razorpay payment link {payload_data['payment_link_id']}",
        data=payload_data,
    )


LIVE_PAYMENT_TOOLS = {
    InterventionType.RETRY_PAYMENT.value: live_retry_payment,
    InterventionType.CREATE_PAYMENT_LINK.value: live_create_payment_link,
}
