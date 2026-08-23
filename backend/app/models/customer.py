from datetime import datetime
from sqlalchemy import Column, String, Float, DateTime
from app.db import Base


class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False, index=True)
    phone = Column(String, nullable=True)
    segment = Column(String, nullable=True)  # e.g., VIP, Enterprise, Standard
    ltv_amount = Column(Float, default=0.0)
    risk_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
