"""Case + agent API (BUILDPLAN Phase 4 · PRD §10, §42).

Read endpoints for cases and their audit timeline, plus the money endpoint:
``POST /cases/{id}/run-agent`` which drives one case through the recovery graph and returns the
final decision, outcome, and timeline.

The run-agent endpoint deliberately does **not** hold a request-scoped ``get_db`` session while the
agent runs — the graph nodes open their own sessions from the injected factory, and on the in-memory
test DB only one session may be active on the shared connection at a time. So it injects
``get_session_factory`` and opens short-lived sessions around the run instead.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent.runner import run_agent
from app.db import get_db, get_session_factory
from app.models.audit import AuditEvent
from app.models.outcome import RecoveryOutcome
from app.schemas.agent import RunAgentResponse, TimelineEntry
from app.schemas.case import RevenueRiskCaseRead
from app.services import case_service

router = APIRouter(prefix="/cases", tags=["Cases"])


def get_checkpointer():
    """Checkpointer for a run. ``None`` lets the runner build its durable SQLite saver; tests
    override this to inject an in-memory ``MemorySaver`` for hermetic runs."""
    return None


@router.get("", response_model=List[RevenueRiskCaseRead])
def list_cases_endpoint(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return case_service.list_cases(db, skip=skip, limit=limit)


@router.get("/{case_id}", response_model=RevenueRiskCaseRead)
def get_case_endpoint(case_id: str, db: Session = Depends(get_db)):
    case = case_service.get_case(db, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return case


@router.get("/{case_id}/audit", response_model=List[TimelineEntry])
def get_case_audit_endpoint(case_id: str, db: Session = Depends(get_db)):
    return _timeline(db, case_id)


@router.post("/{case_id}/run-agent", response_model=RunAgentResponse)
def run_agent_endpoint(
    case_id: str,
    factory: Callable[[], Session] = Depends(get_session_factory),
    checkpointer: Optional[object] = Depends(get_checkpointer),
):
    # Validate the case exists (short-lived session, released before the run).
    db = factory()
    try:
        exists = case_service.get_case_row(db, case_id) is not None
    finally:
        db.close()
    if not exists:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    run_agent(case_id, session_factory=factory, checkpointer=checkpointer)

    db = factory()
    try:
        return _build_response(db, case_id)
    finally:
        db.close()


def _timeline(db: Session, case_id: str) -> List[TimelineEntry]:
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.case_id == case_id)
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        .all()
    )
    return [
        TimelineEntry(
            event_type=e.event_type,
            actor=e.actor,
            payload=e.payload_json or {},
            created_at=e.created_at,
        )
        for e in events
    ]


def _last_ev_choice(db: Session, case_id: str) -> Dict[str, Any]:
    """Recover the final chosen action + its expected_net from the last EV_SCORED audit event."""
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.case_id == case_id, AuditEvent.event_type == "EV_SCORED")
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .all()
    )
    for e in events:
        payload = e.payload_json or {}
        chosen = payload.get("chosen_action")
        if chosen:
            expected_net = None
            for row in payload.get("scored", []):
                if row.get("action") == chosen:
                    expected_net = row.get("expected_net")
                    break
            return {"chosen_action": chosen, "expected_net": expected_net}
    return {"chosen_action": None, "expected_net": None}


def _build_response(db: Session, case_id: str) -> RunAgentResponse:
    case = case_service.get_case_row(db, case_id)
    outcome = (
        db.query(RecoveryOutcome)
        .filter(RecoveryOutcome.case_id == case_id)
        .order_by(RecoveryOutcome.created_at.desc(), RecoveryOutcome.id.desc())
        .first()
    )
    choice = _last_ev_choice(db, case_id)

    return RunAgentResponse(
        case_id=case_id,
        status=case.status if case else "UNKNOWN",
        diagnosis=case.diagnosis_json if case else None,
        chosen_action=choice["chosen_action"],
        expected_net=choice["expected_net"],
        recovered=bool(case and case.status == "RECOVERED"),
        outcome_type=outcome.outcome_type if outcome else None,
        net_recovered=(case.net_recovered_amount or 0.0) if case else 0.0,
        timeline=_timeline(db, case_id),
    )
