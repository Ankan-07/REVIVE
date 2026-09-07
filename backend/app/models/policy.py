from sqlalchemy import Column, String, Boolean, DateTime, JSON
from app.db import Base, utc_now


class Policy(Base):
    __tablename__ = "policies"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=True)
    rules_json = Column(JSON, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
