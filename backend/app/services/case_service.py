from typing import Optional, List
from sqlalchemy.orm import Session
from app.models.case import RevenueRiskCase
from app.schemas.case import RevenueRiskCaseCreate, RevenueRiskCaseRead
from app.schemas.enums import CaseStatus
from app.domain.ids import generate_id
from app.observability import traceable


@traceable(name="service.case.create", run_type="tool")
def create_case(db: Session, data: RevenueRiskCaseCreate) -> RevenueRiskCaseRead:
    case_id = generate_id("RR", db)
    db_obj = RevenueRiskCase(
        id=case_id,
        customer_id=data.customer_id,
        case_type=data.case_type.value if hasattr(data.case_type, "value") else str(data.case_type),
        status=CaseStatus.DETECTED.value,
        amount_at_risk=data.amount_at_risk,
        priority=data.priority.value if hasattr(data.priority, "value") else str(data.priority),
        risk_score=data.risk_score,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return RevenueRiskCaseRead.model_validate(db_obj)


@traceable(name="service.case.get", run_type="tool")
def get_case(db: Session, case_id: str) -> Optional[RevenueRiskCaseRead]:
    db_obj = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == case_id).first()
    if not db_obj:
        return None
    return RevenueRiskCaseRead.model_validate(db_obj)


@traceable(name="service.case.list", run_type="tool")
def list_cases(db: Session, skip: int = 0, limit: int = 100) -> List[RevenueRiskCaseRead]:
    items = db.query(RevenueRiskCase).offset(skip).limit(limit).all()
    return [RevenueRiskCaseRead.model_validate(item) for item in items]


# --------------------------------------------------------------------------------------------------
# Agent-loop mutators (BUILDPLAN Phase 4). The service layer is the ONLY code that mutates a case, so
# every state transition the agent makes flows through one traced, auditable place (PRD §12, §42).
# --------------------------------------------------------------------------------------------------

def _require_row(db: Session, case_id: str) -> RevenueRiskCase:
    row = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == case_id).first()
    if row is None:
        raise LookupError(f"Case {case_id} not found")
    return row


@traceable(name="service.case.get_row", run_type="tool")
def get_case_row(db: Session, case_id: str) -> Optional[RevenueRiskCase]:
    """Return the live ORM row (for the agent's read-side; API reads use :func:`get_case`)."""
    return db.query(RevenueRiskCase).filter(RevenueRiskCase.id == case_id).first()


def _status_value(status) -> str:
    return status.value if hasattr(status, "value") else str(status)


@traceable(name="service.case.set_status", run_type="tool")
def set_status(db: Session, case_id: str, status) -> None:
    row = _require_row(db, case_id)
    row.status = _status_value(status)
    db.commit()


@traceable(name="service.case.set_diagnosis", run_type="tool")
def set_diagnosis(db: Session, case_id: str, diagnosis: dict) -> None:
    row = _require_row(db, case_id)
    row.diagnosis_json = diagnosis
    row.status = CaseStatus.DIAGNOSED.value
    db.commit()


@traceable(name="service.case.set_current_action", run_type="tool")
def set_current_action(db: Session, case_id: str, action: Optional[str]) -> None:
    row = _require_row(db, case_id)
    row.current_action = action
    db.commit()


@traceable(name="service.case.increment_attempt", run_type="tool")
def increment_attempt(db: Session, case_id: str) -> int:
    row = _require_row(db, case_id)
    row.attempt_count = (row.attempt_count or 0) + 1
    db.commit()
    return row.attempt_count


@traceable(name="service.case.set_net_recovered", run_type="tool")
def set_net_recovered(db: Session, case_id: str, amount: float) -> None:
    row = _require_row(db, case_id)
    row.net_recovered_amount = amount
    db.commit()
