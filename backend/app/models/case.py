from sqlalchemy import Column, String, Float, Integer, ForeignKey, DateTime, JSON
from app.db import Base, utc_now


class RevenueRiskCase(Base):
    __tablename__ = "revenue_risk_cases"

    id = Column(String, primary_key=True, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)
    payment_id = Column(String, ForeignKey("payments.id"), nullable=True, index=True)  # the failed payment this case is about (dedup key)
    origin = Column(String, default="lab", server_default="lab", nullable=False, index=True)
    case_type = Column(String, nullable=False, index=True)  # CaseType enum
    status = Column(String, nullable=False, index=True)  # CaseStatus enum
    amount_at_risk = Column(Float, nullable=False)
    net_recovered_amount = Column(Float, default=0.0)
    priority = Column(String, default="MEDIUM")  # Priority enum
    risk_score = Column(Float, default=0.0)
    recovery_probability = Column(Float, nullable=True)  # initial §28 estimate at detection (best of retry/switch/link)
    diagnosis_json = Column(JSON, nullable=True)
    current_action = Column(String, nullable=True)
    attempt_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
