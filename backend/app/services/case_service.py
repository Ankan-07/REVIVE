from typing import Optional, List
from sqlalchemy.orm import Session
from app.models.case import RevenueRiskCase
from app.schemas.case import RevenueRiskCaseCreate, RevenueRiskCaseRead
from app.schemas.enums import CaseStatus
from app.domain.ids import generate_id


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


def get_case(db: Session, case_id: str) -> Optional[RevenueRiskCaseRead]:
    db_obj = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == case_id).first()
    if not db_obj:
        return None
    return RevenueRiskCaseRead.model_validate(db_obj)


def list_cases(db: Session, skip: int = 0, limit: int = 100) -> List[RevenueRiskCaseRead]:
    items = db.query(RevenueRiskCase).offset(skip).limit(limit).all()
    return [RevenueRiskCaseRead.model_validate(item) for item in items]
