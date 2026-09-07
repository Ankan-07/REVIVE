from sqlalchemy import Column, String, ForeignKey, DateTime, Text
from app.db import Base, utc_now


class Escalation(Base):
    __tablename__ = "escalations"

    id = Column(String, primary_key=True, index=True)
    case_id = Column(String, ForeignKey("revenue_risk_cases.id"), nullable=False, index=True)
    reason = Column(String, nullable=False)  # EscalationReason enum
    priority = Column(String, default="HIGH")  # Priority enum
    owner_id = Column(String, nullable=True)
    recommended_action = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="OPEN")  # OPEN, RESOLVED, REJECTED
    created_at = Column(DateTime, default=utc_now)
    resolved_at = Column(DateTime, nullable=True)
