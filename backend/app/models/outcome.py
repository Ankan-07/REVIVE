from sqlalchemy import Column, String, Float, Integer, ForeignKey, DateTime
from app.db import Base, utc_now


class RecoveryOutcome(Base):
    __tablename__ = "recovery_outcomes"

    id = Column(String, primary_key=True, index=True)
    case_id = Column(String, ForeignKey("revenue_risk_cases.id"), nullable=False, index=True)
    outcome_type = Column(String, nullable=False)  # OutcomeType enum
    gross_recovered = Column(Float, default=0.0)
    net_recovered = Column(Float, default=0.0)
    cost_total = Column(Float, default=0.0)
    discount_total = Column(Float, default=0.0)
    gateway_fee_paise = Column(Integer, default=0, nullable=False)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    @property
    def gateway_fee(self) -> float:
        """Returns the gateway fee converted from paise to INR float."""
        return float(self.gateway_fee_paise or 0) / 100.0
