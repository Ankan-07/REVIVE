"""Tests for rate limiting, quotas, 429 responses, and usage audit logging (Phase A2.6)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db, get_session_factory
from app.main import app
from app.models.api_key import KeyUsageEvent
from app.services import api_key_service
from app.services.rate_limiter import RateLimiter, rate_limiter


def test_rate_limiter_unit():
    rl = RateLimiter()
    key_id = "test_key_1"

    # Allow up to 5 req/min
    for _ in range(5):
        allowed, retry_after = rl.check_rate_limit(key_id, limit_per_minute=5)
        assert allowed is True
        assert retry_after == 0

    # 6th request rejected
    allowed, retry_after = rl.check_rate_limit(key_id, limit_per_minute=5)
    assert allowed is False
    assert retry_after > 0


def test_daily_quota_unit():
    rl = RateLimiter()
    key_id = "test_key_2"

    for _ in range(3):
        allowed, retry_after = rl.check_daily_quota(key_id, "run_agent", daily_limit=3)
        assert allowed is True
        assert retry_after == 0

    # 4th request rejected
    allowed, retry_after = rl.check_daily_quota(key_id, "run_agent", daily_limit=3)
    assert allowed is False
    assert retry_after > 0


@pytest.fixture
def rate_limit_env():
    rate_limiter.reset()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_factory] = lambda: TestingSessionLocal

    session = TestingSessionLocal()
    key, raw_key = api_key_service.create_key(session, name="Fast Caller", scopes=["operator"])

    client = TestClient(app)

    yield {
        "client": client,
        "session": session,
        "key": key,
        "raw_key": raw_key,
    }

    app.dependency_overrides.clear()
    rate_limiter.reset()
    session.close()


def test_api_rate_limit_exceeded_returns_429(rate_limit_env):
    client = rate_limit_env["client"]
    raw_key = rate_limit_env["raw_key"]
    session = rate_limit_env["session"]
    key = rate_limit_env["key"]

    headers = {"Authorization": f"Bearer {raw_key}"}

    # Simulate hitting rate limit: 60 requests succeed
    for _ in range(60):
        res = client.get("/cases", headers=headers)
        assert res.status_code == 200

    # 61st request returns 429 Too Many Requests
    res = client.get("/cases", headers=headers)
    assert res.status_code == 429
    assert "Rate limit exceeded" in res.json()["detail"]
    assert "Retry-After" in res.headers

    # Verify audit records written to key_usage_events in DB
    events = session.query(KeyUsageEvent).filter(KeyUsageEvent.key_id == key.id).all()
    assert len(events) == 60
