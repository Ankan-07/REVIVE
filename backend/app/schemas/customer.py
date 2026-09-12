from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr


class CustomerBase(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    segment: Optional[str] = "Standard"
    origin: str = "lab"
    ltv_amount: float = 0.0
    risk_score: float = 0.0


class CustomerCreate(CustomerBase):
    pass


class CustomerRead(CustomerBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
