from sqlalchemy import Column, String, Float, ForeignKey, DateTime
from app.db import Base, utc_now


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(String, primary_key=True, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    due_date = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="OVERDUE")
    pdf_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)
