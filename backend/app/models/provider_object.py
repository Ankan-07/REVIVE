from sqlalchemy import Column, String, Integer, ForeignKey, DateTime
from app.db import Base, utc_now


class ProviderObject(Base):
    """Maps internal revenue risk cases to external payment provider objects (PRD §38, A1.7).
    
    Tracks Razorpay orders, payment links, payments, and invoices with exact paise amounts
    and fees for instant reconciliation (E1) without multiple disjoint provider list queries.
    """
    __tablename__ = "provider_objects"

    id = Column(String, primary_key=True, index=True)
    case_id = Column(String, ForeignKey("revenue_risk_cases.id"), nullable=True, index=True)
    object_type = Column(String, nullable=False)  # 'order', 'link', 'payment', 'invoice'
    provider_object_id = Column(String, unique=True, nullable=False, index=True)
    amount_paise = Column(Integer, nullable=True)
    status = Column(String, nullable=True)
    fee_paise = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
