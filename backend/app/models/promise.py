from sqlalchemy import Column, String, Float, ForeignKey, DateTime
from app.db import Base, utc_now


class PromiseToPay(Base):
    __tablename__ = "promises_to_pay"

    id = Column(String, primary_key=True, index=True)
    case_id = Column(String, ForeignKey("revenue_risk_cases.id"), nullable=False, index=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False, index=True)
    promised_amount = Column(Float, nullable=False)
    promised_date = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="PENDING")  # PromiseStatus enum
    created_at = Column(DateTime, default=utc_now)

    @property
    def promise_date(self):
        return self.promised_date

    @promise_date.setter
    def promise_date(self, val):
        self.promised_date = val

