from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey
from app.db import Base, utc_now


class ApiKey(Base):
    """Service API key model for REVIVE operators and services (Phase A2.1).
    
    Keys are per-person and cryptographically hashed with salted PBKDF2.
    Raw keys are never stored; verification queries by indexed prefix and validates
    against key_hash in constant time.
    """
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)  # Operator or service identity (e.g. "Alice Vance")
    key_prefix = Column(String, unique=True, nullable=False, index=True)  # e.g. "rve_a1b2c3d4"
    key_hash = Column(String, nullable=False)
    salt = Column(String, nullable=False)
    scopes = Column(String, nullable=False)  # Comma-separated scopes: "operator", "internal", "admin"
    revoked = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now)
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)


class KeyUsageEvent(Base):
    """Audit log of key usage events across API endpoints (Phase A2.6)."""
    __tablename__ = "key_usage_events"

    id = Column(String, primary_key=True, index=True)
    key_id = Column(String, ForeignKey("api_keys.id"), nullable=False, index=True)
    route = Column(String, nullable=False)
    method = Column(String, nullable=False)
    ip = Column(String, nullable=True)
    status_code = Column(Integer, nullable=True)
    timestamp = Column(DateTime, default=utc_now, index=True)
