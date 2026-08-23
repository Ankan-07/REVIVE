from datetime import datetime
from sqlalchemy import Column, String, Float, ForeignKey, DateTime, JSON
from app.db import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(String, primary_key=True, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="INR")
    status = Column(String, nullable=False)
    items_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
