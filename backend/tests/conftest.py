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

