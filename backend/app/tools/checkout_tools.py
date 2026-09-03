"""Simulated checkout-recovery tools (PRD §17, §18, §28, §38, §39).

Each tool is a thin declaration over :func:`app.tools.runner.run_action_tool`, which owns the shared
§18/§38/§39 pipeline (auth, parameter validation, idempotent replay, audit, deterministic
simulation, and Intervention persistence).  The checkout-specific parts are the oracle
(:mod:`app.simulation.checkout_sim`), the ``CHK-NNNNN`` entity-id format, and the failure
classification — a failed checkout outreach is a non-retryable user-side outcome.
"""
from __future__ import annotations

from typing import Callable, Dict

from sqlalchemy.orm import Session

from app.schemas.enums import InterventionType
from app.simulation import checkout_sim
from app.tools import runner
from app.tools.base import FailureCategory, ToolResult


def _run_checkout_action(
    db: Session,
    *,
    case_id: str,
    checkout_id: str,
    action: str,
    attempt: int,
    caller: str,
) -> ToolResult:
    return runner.run_action_tool(
        db,
        case_id=case_id,
        entity_id=checkout_id,
        action=action,
        attempt=attempt,
        caller=caller,
        entity_prefix="CHK",
        simulate=checkout_sim.simulate_checkout_action,
        not_found_exception=checkout_sim.CheckoutNotFoundError,
        not_found_code="CHECKOUT_NOT_FOUND",
        entity_label="checkout",
        failure_code="CHECKOUT_ACTION_FAILED",
        category_of=lambda db, sim, error_code: FailureCategory.NON_RETRYABLE_USER_FAILURE,
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
