from sqlalchemy import Column, String, Integer, DateTime, JSON
from app.db import Base, utc_now


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id = Column(String, primary_key=True, index=True)
    seed = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    config_json = Column(JSON, nullable=True)
    metrics_json = Column(JSON, nullable=True)
    status = Column(String, nullable=False, default="COMPLETED")
    created_at = Column(DateTime, default=utc_now)
