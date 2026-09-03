"""Simulated invoice-recovery tools (PRD §17, §18, §28, §38, §39).

Each tool is a thin declaration over :func:`app.tools.runner.run_action_tool`, which owns the shared
§18/§38/§39 pipeline (auth, parameter validation, idempotent replay, audit, deterministic
simulation, and Intervention persistence).  The invoice-specific parts are the oracle
(:mod:`app.simulation.invoice_sim`), the ``INV-NNNNN`` entity-id format, and the failure
classification — a failed invoice action is a non-retryable user-side outcome.
"""
from __future__ import annotations

from typing import Callable, Dict

from sqlalchemy.orm import Session

from app.schemas.enums import InterventionType
from app.simulation import invoice_sim
from app.tools import runner
from app.tools.base import FailureCategory, ToolResult


def _run_invoice_action(
    db: Session,
    *,
    case_id: str,
    invoice_id: str,
    action: str,
    attempt: int,
    caller: str,
) -> ToolResult:
    return runner.run_action_tool(
        db,
        case_id=case_id,
        entity_id=invoice_id,
        action=action,
        attempt=attempt,
        caller=caller,
        entity_prefix="INV",
        simulate=invoice_sim.simulate_invoice_action,
        not_found_exception=invoice_sim.InvoiceNotFoundError,
        not_found_code="INVOICE_NOT_FOUND",
        entity_label="invoice",
        failure_code="INVOICE_ACTION_FAILED",
        category_of=lambda db, sim, error_code: FailureCategory.NON_RETRYABLE_USER_FAILURE,
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
