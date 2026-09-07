from sqlalchemy import Column, String, Boolean, DateTime, JSON
from app.db import Base, utc_now


class ProviderEvent(Base):
    """Stores incoming webhook events from payment providers (e.g. Razorpay).
    
    The razorpay_event_id has a database-level UNIQUE constraint to ensure strict
    at-most-once processing across retries (PRD idempotency constraint, A1.3).
    """
    __tablename__ = "provider_events"

    id = Column(String, primary_key=True, index=True)
    provider = Column(String, nullable=False, default="razorpay")
    razorpay_event_id = Column(String, unique=True, nullable=False, index=True)
    event_type = Column(String, nullable=True)
    payload_json = Column(JSON, nullable=True)
    processed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utc_now)
