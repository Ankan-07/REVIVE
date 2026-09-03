from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


from app.schemas.enums import EscalationResolutionStatus


class EscalationAssignRequest(BaseModel):
    owner_id: str


class EscalationResolveRequest(BaseModel):
    resolution_status: EscalationResolutionStatus
    notes: Optional[str] = None


class EscalationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    reason: str
    priority: str
    owner_id: Optional[str] = None
    recommended_action: Optional[str] = None
    notes: Optional[str] = None
    status: str
    created_at: datetime
    resolved_at: Optional[datetime] = None
