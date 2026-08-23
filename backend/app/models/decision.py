from datetime import datetime
from sqlalchemy import Column, String, ForeignKey, DateTime, JSON, Text
from app.db import Base


class AgentDecision(Base):
    __tablename__ = "agent_decisions"

    id = Column(String, primary_key=True, index=True)
    case_id = Column(String, ForeignKey("revenue_risk_cases.id"), nullable=False, index=True)
    node_name = Column(String, nullable=False)
    input_state_json = Column(JSON, nullable=True)
    output_decision_json = Column(JSON, nullable=True)
    reasoning = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
