from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, ForeignKey, DateTime
from app.db import Base


class Payment(Base):
    __tablename__ = "payments"

    id = Column(String, primary_key=True, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)
    order_id = Column(String, ForeignKey("orders.id"), nullable=True, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="INR")
    gateway = Column(String, nullable=False)
    status = Column(String, nullable=False)  # PaymentStatus enum value
    error_code = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    attempt_count = Column(Integer, default=1)
    method_health = Column(Float, default=1.0)  # §28 payment-instrument health [0,1]
    recovery_roll = Column(Float, default=0.0)  # stored uniform draw; makes outcome deterministic + idempotent
    created_at = Column(DateTime, default=datetime.utcnow)
