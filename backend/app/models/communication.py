from sqlalchemy import Column, String, ForeignKey, DateTime, Text
from app.db import Base, utc_now


class Communication(Base):
    __tablename__ = "communications"

    id = Column(String, primary_key=True, index=True)
    case_id = Column(String, ForeignKey("revenue_risk_cases.id"), nullable=False, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)
    channel = Column(String, nullable=False)  # ChannelType enum
    recipient = Column(String, nullable=False)
    template_id = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="SENT")
    sent_at = Column(DateTime, default=utc_now)
    provider = Column(String, nullable=True, default="mock_comms")
    provider_message_id = Column(String, nullable=True, index=True)
    delivered_at = Column(DateTime, nullable=True)
    reply_body = Column(Text, nullable=True)

