from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.schemas.enums import PromiseStatus


class PromiseToPayBase(BaseModel):
    case_id: str
    customer_id: str
    promised_amount: float
    promised_date: datetime


class PromiseToPayCreate(PromiseToPayBase):
    pass


class PromiseToPayRead(PromiseToPayBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: PromiseStatus
    created_at: datetime
