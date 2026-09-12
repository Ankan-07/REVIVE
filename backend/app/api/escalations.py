from typing import Callable, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agent.runner import resume_agent
from app.api.cases import get_checkpointer
from app.auth import AuthContext, require_api_key
from app.db import get_db, get_session_factory
from app.schemas.escalation import EscalationAssignRequest, EscalationRead, EscalationResolveRequest
from app.services import escalation_service

router = APIRouter(prefix="/escalations", tags=["Escalations"], dependencies=[Depends(require_api_key("operator"))])


@router.get("", response_model=List[EscalationRead])
def list_pending_escalations_endpoint(db: Session = Depends(get_db)):
    """List all pending (OPEN) escalations in the queue."""
    return escalation_service.get_pending_escalations(db)


@router.get("/{escalation_id}", response_model=EscalationRead)
def get_escalation_endpoint(escalation_id: str, db: Session = Depends(get_db)):
    """Get details for a specific escalation."""
    esc = escalation_service.get_escalation(db, escalation_id)
    if not esc:
        raise HTTPException(status_code=404, detail=f"Escalation {escalation_id} not found")
    return esc


@router.post("/{escalation_id}/assign", response_model=EscalationRead)
def assign_escalation_endpoint(
    escalation_id: str,
    body: EscalationAssignRequest,
    auth: AuthContext = Depends(require_api_key("operator")),
    db: Session = Depends(get_db)
):
    """Assign an open escalation ticket to an operator (Phase A2.4)."""
    assigned_owner = body.owner_id
    if not assigned_owner or assigned_owner == "CurrentOperator":
        assigned_owner = auth.name
    esc = escalation_service.assign_escalation(db, escalation_id, assigned_owner)
    if not esc:
        raise HTTPException(status_code=404, detail=f"Open escalation {escalation_id} not found")
    return esc


@router.post("/{escalation_id}/resolve", response_model=EscalationRead)
def resolve_escalation_endpoint(
    escalation_id: str,
    body: EscalationResolveRequest,
    auth: AuthContext = Depends(require_api_key("operator")),
    factory: Callable[[], Session] = Depends(get_session_factory),
    checkpointer: Optional[object] = Depends(get_checkpointer),
):
    """Resolve an escalation (e.g. APPROVED or REJECTED) and resume graph execution if approved."""
    db = factory()
    try:
        esc = escalation_service.get_escalation(db, escalation_id)
        if not esc:
            raise HTTPException(status_code=404, detail=f"Escalation {escalation_id} not found")
        case_id = esc.case_id

        resolved_esc, transitioned = escalation_service.resolve_escalation(
            db,
            escalation_id,
            resolution_status=body.resolution_status.value,
            notes=body.notes
        )
    finally:
        db.close()

    if transitioned and body.resolution_status in ("APPROVED", "REJECTED"):
        resume_agent(case_id, resolution=body.resolution_status.value, session_factory=factory, checkpointer=checkpointer, caller="operator")

    db = factory()
    try:
        updated_esc = escalation_service.get_escalation(db, escalation_id)
        return updated_esc
    finally:
        db.close()
