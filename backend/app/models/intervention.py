from sqlalchemy import Column, String, Float, ForeignKey, DateTime, JSON
from app.db import Base, utc_now


class Intervention(Base):
    __tablename__ = "interventions"

    id = Column(String, primary_key=True, index=True)
    case_id = Column(String, ForeignKey("revenue_risk_cases.id"), nullable=False, index=True)
    idempotency_key = Column(String, unique=True, index=True, nullable=True)
    intervention_type = Column(String, nullable=False)  # InterventionType enum
    cost = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    status = Column(String, nullable=False, default="PENDING")
    payload_json = Column(JSON, nullable=True)
    executed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
