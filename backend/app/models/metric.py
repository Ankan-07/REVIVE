from sqlalchemy import Column, String, Float, DateTime
from app.db import Base, utc_now


class GatewayMetric(Base):
    __tablename__ = "gateway_metrics"

    id = Column(String, primary_key=True, index=True)
    gateway_name = Column(String, nullable=False, index=True)
    success_rate = Column(Float, nullable=False)
    baseline_success_rate = Column(Float, nullable=True)  # §13 diagnosis: current vs baseline
    latency_ms = Column(Float, nullable=False)
    health_status = Column(String, nullable=False, default="HEALTHY")  # HEALTHY, DEGRADED, DOWN
    recorded_at = Column(DateTime, default=utc_now)
