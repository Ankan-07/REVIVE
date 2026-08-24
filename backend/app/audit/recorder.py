"""Audit event writer (PRD §8.5, §42; BUILDPLAN §7).

A single tiny helper called on every state transition, decision, tool call, and human override.
Auditability is a *feature* here, not logging: every autonomous financial action must leave a
structured, queryable trail (PRD §4 principle 4, §58.6).

The row shape matches the existing inline writer in
:mod:`app.services.event_service` (which emits ``CASE_CREATED``), so the Phase 4 timeline reads as
one continuous history from detection through recovery.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.domain.ids import generate_id
from app.observability import traceable


@traceable(name="audit.record", run_type="tool")
def record(
    db: Session,
    case_id: Optional[str],
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    actor: str = "AGENT",
    *,
    commit: bool = True,
) -> AuditEvent:
    """Append one audit event for ``case_id`` and return the persisted row.

    ``actor`` is one of ``AGENT`` | ``SYSTEM`` | ``HUMAN`` (matches the model default). Pass
    ``commit=False`` to batch several audit rows inside a caller-managed transaction.
    """
    audit = AuditEvent(
        id=generate_id("AUD", db),
        case_id=case_id,
        event_type=event_type,
        actor=actor,
        payload_json=payload or {},
    )
    db.add(audit)
    if commit:
        db.commit()
        db.refresh(audit)
    return audit
