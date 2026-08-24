"""Simulated payment-recovery tools (PRD §17, §28, §38, §39).

Each tool wraps the deterministic :mod:`app.simulation.payment_sim` oracle with persistence, an audit
trail, and idempotency. The oracle decides *whether the money comes back* (``success = roll < p``);
these tools record that outcome as an :class:`~app.models.intervention.Intervention` and return a
uniform :class:`~app.tools.base.ToolResult`. They perform the only real "side effects" in the system.

Idempotency (§38): a tool call is keyed on ``case_id:action:attempt``. Replaying the same key returns
the stored result and creates no second intervention row — so a retried/resumed run is safe.
"""
from __future__ import annotations

from typing import Callable, Dict

from sqlalchemy.orm import Session

from app.agent.costs import cost_of
from app.models.payment import Payment
from app.observability import traceable
from app.schemas.enums import InterventionType, PaymentStatus
from app.services import intervention_service
from app.simulation import payment_sim
from app.tools.base import ToolResult, idempotency_key


def _run_action(db: Session, *, case_id: str, payment_id: str, action: str, attempt: int) -> ToolResult:
    """Shared body for the payment-attempt tools: idempotent simulate-and-persist."""
    key = idempotency_key(case_id, action, attempt)

    existing = intervention_service.get_by_idempotency_key(db, case_id, key)
    if existing is not None:
        payload = existing.payload_json or {}
        success = bool(payload.get("success"))
        return ToolResult(
            tool=action,
            success=success,
            retryable=not success,
            detail="idempotent replay of a prior attempt",
            data={k: v for k, v in payload.items() if k != "idempotency_key"},
        )

    try:
        sim = payment_sim.simulate_payment(db, payment_id, action, attempt)
    except payment_sim.PaymentNotFoundError:
        return ToolResult(
            tool=action, success=False, error_code="PAYMENT_NOT_FOUND", retryable=False,
            detail=f"payment {payment_id} not found",
        )

    intervention_service.create_executed(
        db, case_id=case_id, action=action, cost=cost_of(action), idempotency_key=key, result=sim
    )
    success = bool(sim["success"])
    return ToolResult(
        tool=action,
        success=success,
        retryable=not success,
        detail=f"p={sim['probability']} via {sim['gateway_used']} (roll={sim['recovery_roll']})",
        data=sim,
    )


@traceable(name="tool.check_payment_status", run_type="tool")
def check_payment_status(db: Session, payment_id: str) -> ToolResult:
    """Read-only status probe for a payment (no side effect, PRD §17)."""
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment is None:
        return ToolResult(
            tool="check_payment_status", success=False, error_code="PAYMENT_NOT_FOUND",
            retryable=False, detail=f"payment {payment_id} not found",
        )
    return ToolResult(
        tool="check_payment_status",
        success=payment.status == PaymentStatus.SUCCEEDED.value,
        retryable=payment.status == PaymentStatus.FAILED.value,
        detail=f"status={payment.status}",
        data={"status": payment.status, "gateway": payment.gateway, "error_code": payment.error_code},
    )


@traceable(name="tool.retry_payment", run_type="tool")
def retry_payment(db: Session, *, case_id: str, payment_id: str, attempt: int) -> ToolResult:
    """Retry the payment on its current gateway (PRD §17)."""
    return _run_action(
        db, case_id=case_id, payment_id=payment_id,
        action=InterventionType.RETRY_PAYMENT.value, attempt=attempt,
    )


@traceable(name="tool.switch_gateway", run_type="tool")
def switch_gateway(db: Session, *, case_id: str, payment_id: str, attempt: int) -> ToolResult:
    """Re-attempt the payment on the healthiest alternative gateway (PRD §17)."""
    return _run_action(
        db, case_id=case_id, payment_id=payment_id,
        action=InterventionType.SWITCH_GATEWAY.value, attempt=attempt,
    )


@traceable(name="tool.create_payment_link", run_type="tool")
def create_payment_link(db: Session, *, case_id: str, payment_id: str, attempt: int) -> ToolResult:
    """Issue a hosted payment link so the customer can re-pay on a healthy instrument (PRD §17)."""
    return _run_action(
        db, case_id=case_id, payment_id=payment_id,
        action=InterventionType.CREATE_PAYMENT_LINK.value, attempt=attempt,
    )


# Dispatch table so the execute_tool node can select a tool from the chosen action string.
TOOL_FOR_ACTION: Dict[str, Callable[..., ToolResult]] = {
    InterventionType.RETRY_PAYMENT.value: retry_payment,
    InterventionType.SWITCH_GATEWAY.value: switch_gateway,
    InterventionType.CREATE_PAYMENT_LINK.value: create_payment_link,
}
