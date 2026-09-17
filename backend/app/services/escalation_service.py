from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.domain.ids import generate_id
from app.models.escalation import Escalation

def get_pending_escalations(db: Session) -> List[Escalation]:
    """Return all escalations currently waiting for human action."""
    return db.query(Escalation).filter(Escalation.status == "OPEN").order_by(Escalation.created_at.desc()).all()

def get_escalation(db: Session, escalation_id: str, for_update: bool = False) -> Optional[Escalation]:
    query = db.query(Escalation).filter(Escalation.id == escalation_id)
    if for_update:
        query = query.with_for_update()
    return query.first()

def get_open_for_case(db: Session, case_id: str) -> Optional[Escalation]:
    return db.query(Escalation).filter(Escalation.case_id == case_id, Escalation.status == "OPEN").first()

def create_escalation(
    db: Session, 
    *,
    case_id: str, 
    reason: str, 
    priority: str = "HIGH", 
    recommended_action: Optional[str] = None,
    notes: Optional[str] = None
) -> Escalation:
    """Create a new escalation for a case, returning the existing one if it's already open."""
    existing = get_open_for_case(db, case_id)
    if existing:
        return existing
        
    escalation_id = generate_id("ESC", db)
    esc = Escalation(
        id=escalation_id,
        case_id=case_id,
        reason=reason,
        priority=priority,
        recommended_action=recommended_action,
        notes=notes,
        status="OPEN"
    )
    db.add(esc)
    db.commit()
    db.refresh(esc)
    return esc

def assign_escalation(db: Session, escalation_id: str, owner_id: str) -> Optional[Escalation]:
    """Assign an open escalation to an operator."""
    esc = get_escalation(db, escalation_id, for_update=True)
    if esc and esc.status == "OPEN":
        esc.owner_id = owner_id
        db.commit()
        db.refresh(esc)
    return esc

import threading

_escalation_lock = threading.Lock()

def resolve_escalation(
    db: Session, 
    escalation_id: str, 
    resolution_status: str, 
    notes: Optional[str] = None
) -> tuple[Optional[Escalation], bool]:
    """Resolve an escalation and return a boolean indicating if a state transition occurred."""
    with _escalation_lock:
        esc = get_escalation(db, escalation_id, for_update=True)
        transitioned = False
        if esc and esc.status == "OPEN":
            esc.status = resolution_status
            if notes:
                existing_notes = esc.notes or ""
                sep = "\n\n" if existing_notes else ""
                esc.notes = f"{existing_notes}{sep}Resolution: {notes}"
            esc.resolved_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(esc)
            transitioned = True
        return esc, transitioned
