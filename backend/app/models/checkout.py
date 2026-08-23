from datetime import datetime
from sqlalchemy import Column, String, Float, ForeignKey, DateTime, JSON
from app.db import Base


class Checkout(Base):
    __tablename__ = "checkouts"

    id = Column(String, primary_key=True, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)
    cart_value = Column(Float, nullable=False)
    items_json = Column(JSON, nullable=True)
    abandoned_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, nullable=False, default="ABANDONED")
    created_at = Column(DateTime, default=datetime.utcnow)
