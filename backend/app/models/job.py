from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, JSON, Text
from app.db import Base, utc_now


class Job(Base):
    """Tracks background asynchronous jobs executed by the ARQ worker (Phase A4).

    Provides durable state persistence, dead-letter visibility, failure stack traces,
    and progress tracking independently of transient in-memory Redis keys.
    """
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, index=True)
    job_type = Column(String(64), nullable=False, index=True)  # 'run_agent', 'verify_promises', 'reconcile', etc.
    status = Column(String(32), nullable=False, default="QUEUED", index=True)  # 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED'
    case_id = Column(String(36), ForeignKey("revenue_risk_cases.id"), nullable=True, index=True)
    payload_json = Column(JSON, nullable=True)
    result_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    traceback = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
