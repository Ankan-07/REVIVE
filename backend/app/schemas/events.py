from pydantic import BaseModel
from typing import Optional, Any, Dict, List
from app.schemas.enums import EventType


class EventPayload(BaseModel):
    event_type: EventType
    customer_id: Optional[str] = None
    payment_id: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = "INR"
    details: Optional[Dict[str, Any]] = None


class DetectionResult(BaseModel):
    payment_id: str
    status_code: int
    body: Dict[str, Any]


class DetectionSummary(BaseModel):
    scanned: int
    cases_created: int
    already_cased: int
    errors: int
    results: List[DetectionResult]
