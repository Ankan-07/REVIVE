"""Pytest configuration and global fixtures for REVIVE test suite."""
import pytest
from app.auth import AuthContext, get_current_auth
from app.main import app


@pytest.fixture(autouse=True)
def default_auth_override(request):
    """Automatically provide valid operator/admin credentials for functional tests.
    
    Tests that specifically test authentication, authorization, session cookies,
    or rate limits (test_auth_*, test_rate_limiter, test_api_keys) are excluded so
    they exercise the real, un-mocked authentication layer.
    """
    test_file = request.node.fspath.basename
    if any(prefix in test_file for prefix in ("test_auth", "test_rate_limiter", "test_api_keys")):
        yield
        return

    admin_auth = AuthContext(
        key_id="test_fixture_admin",
        name="Test Operator",
        scopes={"admin", "operator", "internal"},
        is_session=False,
    )
    app.dependency_overrides[get_current_auth] = lambda: admin_auth
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_auth, None)


@pytest.fixture(autouse=True)
def fallback_razorpay_keys(monkeypatch, request):
    """Fallback placeholder test keys when real keys are absent.
    
    If real keys are present in the environment or .env, they are preserved as primary.
    Only when absent do we provide mock test keys starting with 'rzp_test_'.
    Excluded for test files that test missing keys explicitly.
    """
    test_file = request.node.fspath.basename
    if test_file == "test_razorpay_fallback.py":
        yield
        return

    import os
    if not os.getenv("RAZORPAY_KEY_ID"):
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_placeholder_key")
    if not os.getenv("RAZORPAY_KEY_SECRET"):
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "placeholder_secret_xyz")
    if not os.getenv("RAZORPAY_WEBHOOK_SECRET"):
        monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "placeholder_webhook_sec")
    yield


@pytest.fixture
def factory():
    """A session factory bound to a fresh in-memory DB for hermetic test execution."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.db import Base
    import app.models  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)

