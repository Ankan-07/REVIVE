from datetime import datetime
from typing import Optional, Any, Dict
from pydantic import BaseModel, ConfigDict
from app.schemas.enums import CaseStatus, CaseType, Priority


class RevenueRiskCaseBase(BaseModel):
    customer_id: str
    case_type: CaseType
    amount_at_risk: float
    origin: str = "lab"
    priority: Priority = Priority.MEDIUM
    risk_score: float = 0.0


class RevenueRiskCaseCreate(RevenueRiskCaseBase):
    pass


class RevenueRiskCaseRead(RevenueRiskCaseBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    payment_id: Optional[str] = None
    status: CaseStatus
    net_recovered_amount: float = 0.0
    diagnosis_json: Optional[Dict[str, Any]] = None
    details: Optional[Dict[str, Any]] = None
    current_action: Optional[str] = None
    attempt_count: int = 0
    created_at: datetime
    updated_at: datetime
