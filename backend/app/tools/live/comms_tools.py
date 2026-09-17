"""Live communication outreach recovery tools (PRD §17, §18, §38, Phase C).

Uses MockCommsProvider to execute tracked outreach (email/SMS/payment plan)
without third-party vendor compliance burdens.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.agent.costs import cost_of
from app.comms import get_comms_provider
from app.models.customer import Customer
from app.models.intervention import Intervention
from app.schemas.enums import ChannelType, InterventionType
from app.services import case_service, intervention_service
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
        detail="idempotent replay of prior live comms attempt",
        data={k: v for k, v in payload.items() if k not in ("idempotency_key",)},
        retryable=not success,
    )


def live_send_reminder(
    db: Session,
    *,
    case_id: str,
    attempt: int,
    caller: str = "system",
    **kwargs: Any,
) -> ToolResult:
    """Send payment/recovery reminder outreach via MockCommsProvider (Phase C)."""
    try:
        require_system_context(caller)
        validate_tool_params(case_id=case_id, attempt=attempt)
    except (AuthorizationError, ValidationError) as exc:
        return ToolResult(
            tool=InterventionType.SEND_REMINDER.value,
            success=False,
            error_code="VALIDATION_ERROR",
            detail=str(exc),
            retryable=False,
        )

    # Idempotency check (§38)
    idemp_key = f"{case_id}:reminder:{attempt}"
    existing = intervention_service.get_by_idempotency_key(db, case_id, idemp_key)
    if existing:
        return _replay_intervention(InterventionType.SEND_REMINDER.value, existing)

    case = case_service.get_case_row(db, case_id)
    if not case:
        return ToolResult(
            tool=InterventionType.SEND_REMINDER.value,
            success=False,
            error_code="CASE_NOT_FOUND",
            detail=f"Case {case_id} not found",
            retryable=False,
        )

    customer = db.query(Customer).filter(Customer.id == case.customer_id).first()
    recipient = (customer.email or customer.phone) if customer else "customer@example.com"
    channel = ChannelType.EMAIL.value if ("@" in recipient) else ChannelType.SMS.value

    comms = get_comms_provider()
    comms_res = comms.send(
        db,
        case_id=case_id,
        customer_id=case.customer_id,
        recipient=recipient,
        channel=channel,
        template_id="payment_reminder",
        context={
            "customer_name": customer.name if customer else "Customer",
            "amount": case.amount_at_risk,
            "payment_link": f"https://rzp.io/l/pay_{case_id}",
        },
    )

    if not comms_res.success:
        return ToolResult(
            tool=InterventionType.SEND_REMINDER.value,
            success=False,
            error_code="COMMS_DELIVERY_FAILED",
            detail=comms_res.error or "Comms delivery failed",
            retryable=True,
            failure_category=FailureCategory.RETRYABLE_SYSTEM_FAILURE,
        )

    cost = cost_of(InterventionType.SEND_REMINDER.value)
    payload_data = {
        "success": True,
        "action": InterventionType.SEND_REMINDER.value,
        "attempt": attempt,
        "channel": channel,
        "recipient": recipient,
        "provider": comms_res.provider,
        "provider_message_id": comms_res.provider_message_id,
        "communication_id": comms_res.communication_id,
    }

    intervention_service.create_executed(
        db,
        case_id=case_id,
        action=InterventionType.SEND_REMINDER.value,
        cost=cost,
        idempotency_key=idemp_key,
        result=payload_data,
    )

    return ToolResult(
        tool=InterventionType.SEND_REMINDER.value,
        success=True,
        detail=f"Sent reminder outreach {comms_res.provider_message_id}",
        data=payload_data,
    )


def live_send_discount_message(
    db: Session,
    *,
    case_id: str,
    attempt: int,
    caller: str = "system",
    discount_percent: int = 10,
    **kwargs: Any,
) -> ToolResult:
    """Send checkout discount incentive outreach via MockCommsProvider (Phase C)."""
    try:
        require_system_context(caller)
        validate_tool_params(case_id=case_id, attempt=attempt)
    except (AuthorizationError, ValidationError) as exc:
        return ToolResult(
            tool=InterventionType.SEND_DISCOUNT_MESSAGE.value,
            success=False,
            error_code="VALIDATION_ERROR",
            detail=str(exc),
            retryable=False,
        )

    idemp_key = f"{case_id}:discount:{attempt}"
    existing = intervention_service.get_by_idempotency_key(db, case_id, idemp_key)
    if existing:
        return _replay_intervention(InterventionType.SEND_DISCOUNT_MESSAGE.value, existing)

    case = case_service.get_case_row(db, case_id)
    if not case:
        return ToolResult(
            tool=InterventionType.SEND_DISCOUNT_MESSAGE.value,
            success=False,
            error_code="CASE_NOT_FOUND",
            detail=f"Case {case_id} not found",
            retryable=False,
        )

    customer = db.query(Customer).filter(Customer.id == case.customer_id).first()
    recipient = (customer.email or customer.phone) if customer else "shopper@example.com"
    channel = ChannelType.EMAIL.value if ("@" in recipient) else ChannelType.SMS.value

    comms = get_comms_provider()
    comms_res = comms.send(
        db,
        case_id=case_id,
        customer_id=case.customer_id,
        recipient=recipient,
        channel=channel,
        template_id="discount_offer",
        context={
            "customer_name": customer.name if customer else "Valued Shopper",
            "amount": case.amount_at_risk,
            "discount_percent": discount_percent,
            "discount_code": f"SAVE{discount_percent}",
            "payment_link": f"https://rzp.io/l/chk_{case_id}",
        },
    )

    if not comms_res.success:
        return ToolResult(
            tool=InterventionType.SEND_DISCOUNT_MESSAGE.value,
            success=False,
            error_code="COMMS_DELIVERY_FAILED",
            detail=comms_res.error or "Comms delivery failed",
            retryable=True,
            failure_category=FailureCategory.RETRYABLE_SYSTEM_FAILURE,
        )

    cost = cost_of(InterventionType.SEND_DISCOUNT_MESSAGE.value)
    payload_data = {
        "success": True,
        "action": InterventionType.SEND_DISCOUNT_MESSAGE.value,
        "attempt": attempt,
        "discount_percent": discount_percent,
        "channel": channel,
        "recipient": recipient,
        "provider": comms_res.provider,
        "provider_message_id": comms_res.provider_message_id,
        "communication_id": comms_res.communication_id,
    }

    intervention_service.create_executed(
        db,
        case_id=case_id,
        action=InterventionType.SEND_DISCOUNT_MESSAGE.value,
        cost=cost,
        idempotency_key=idemp_key,
        result=payload_data,
    )

    return ToolResult(
        tool=InterventionType.SEND_DISCOUNT_MESSAGE.value,
        success=True,
        detail=f"Sent discount offer outreach {comms_res.provider_message_id}",
        data=payload_data,
    )


def live_offer_payment_plan(
    db: Session,
    *,
    case_id: str,
    attempt: int,
    caller: str = "system",
    **kwargs: Any,
) -> ToolResult:
    """Send payment plan offer outreach via MockCommsProvider (Phase C)."""
    return live_send_reminder(db, case_id=case_id, attempt=attempt, caller=caller, **kwargs)


LIVE_COMMS_TOOLS = {
    InterventionType.SEND_REMINDER.value: live_send_reminder,
    InterventionType.SEND_DISCOUNT_MESSAGE.value: live_send_discount_message,
    InterventionType.OFFER_PAYMENT_PLAN.value: live_offer_payment_plan,
}
