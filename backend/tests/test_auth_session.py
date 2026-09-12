"""Tests for frontend session cookie authentication flow (Phase A2.5)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import SESSION_COOKIE_NAME
from app.db import Base, get_db, get_session_factory
from app.main import app
from app.services import api_key_service


@pytest.fixture
def session_client():
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
    key, raw_key = api_key_service.create_key(session, name="Dana Scully", scopes=["operator"])

    client = TestClient(app)

    yield {
        "client": client,
        "session": session,
        "key": key,
        "raw_key": raw_key,
    }

    app.dependency_overrides.clear()
    session.close()


def test_session_login_invalid_key_fails(session_client):
    client = session_client["client"]
    res = client.post("/auth/session", json={"api_key": "rve_bad_badbadbadbadbad"})
    assert res.status_code == 401
    assert "revive_session" not in res.cookies


def test_session_login_success_sets_httponly_cookie(session_client):
    client = session_client["client"]
    raw_key = session_client["raw_key"]

    res = client.post("/auth/session", json={"api_key": raw_key})
    assert res.status_code == 200
    data = res.json()
    assert data["authenticated"] is True
    assert data["name"] == "Dana Scully"
    assert "operator" in data["scopes"]

    # Check cookie set
    assert SESSION_COOKIE_NAME in res.cookies
    cookie = res.cookies[SESSION_COOKIE_NAME]
    assert cookie is not None


def test_session_cookie_authenticates_requests(session_client):
    client = session_client["client"]
    raw_key = session_client["raw_key"]

    # Login to acquire session cookie
    login_res = client.post("/auth/session", json={"api_key": raw_key})
    assert login_res.status_code == 200

    # TestClient automatically retains cookies
    me_res = client.get("/auth/me")
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["name"] == "Dana Scully"
    assert me_data["is_session"] is True
    assert "operator" in me_data["scopes"]

    # Access protected /cases endpoint with session cookie
    cases_res = client.get("/cases")
    assert cases_res.status_code == 200


def test_revoking_key_immediately_invalidates_session(session_client):
    client = session_client["client"]
    session = session_client["session"]
    key = session_client["key"]
    raw_key = session_client["raw_key"]

    login_res = client.post("/auth/session", json={"api_key": raw_key})
    assert login_res.status_code == 200

    # Verify session works
    assert client.get("/auth/me").status_code == 200

    # Revoke key in DB
    api_key_service.revoke_key(session, key.id)

    # Immediate rejection on next call
    assert client.get("/auth/me").status_code == 401


def test_session_logout(session_client):
    client = session_client["client"]
    raw_key = session_client["raw_key"]

    client.post("/auth/session", json={"api_key": raw_key})
    assert client.get("/auth/me").status_code == 200

    # Logout
    logout_res = client.post("/auth/logout")
    assert logout_res.status_code == 200
    assert logout_res.json()["status"] == "logged_out"

    # Subsequent requests are unauthenticated
    assert client.get("/auth/me").status_code == 401
