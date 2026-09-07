from sqlalchemy import Column, String, Float, DateTime
from app.db import Base, utc_now


class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, index=True)
    phone = Column(String, nullable=True)
    segment = Column(String, nullable=True)  # e.g., VIP, Enterprise, Standard
    origin = Column(String, default="lab", server_default="lab", nullable=False, index=True)
    ltv_amount = Column(Float, default=0.0)
    risk_score = Column(Float, default=0.0)
    intent_score = Column(Float, default=0.0)  # §28 customer_intent: propensity to complete payment
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
