from sqlalchemy import Column, String, ForeignKey, DateTime
from app.db import Base, utc_now


class CaseRunLock(Base):
    """Per-case execution registry and distributed concurrency control (Phase B4.3).

    Guarantees single-flight LangGraph invocation per case across webhook handlers,
    operator dashboard actions, and scheduled background workers.
    """
    __tablename__ = "case_run_locks"

    id = Column(String(36), primary_key=True, index=True)
    case_id = Column(String(36), ForeignKey("revenue_risk_cases.id"), unique=True, nullable=False, index=True)
    state = Column(String(32), nullable=False, default="released", index=True)  # queued, running, terminal, released
    locked_at = Column(DateTime, nullable=True)
    locked_by_job_id = Column(String(64), nullable=True)
    lock_token = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
