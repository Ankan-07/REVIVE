from datetime import datetime
from sqlalchemy import Column, String, ForeignKey, DateTime, JSON
from app.db import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String, primary_key=True, index=True)
    case_id = Column(String, ForeignKey("revenue_risk_cases.id"), nullable=True, index=True)
    event_type = Column(String, nullable=False, index=True)
    actor = Column(String, nullable=False, default="AGENT")  # AGENT, SYSTEM, HUMAN
    payload_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
