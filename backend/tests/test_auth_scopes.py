"""Tests for route scoping, unauthenticated 401 rejection, and production guards (Phase A2.3, A2.4)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db, get_session_factory
from app.main import app
from app.models.api_key import ApiKey
from app.models.escalation import Escalation
from app.models.case import RevenueRiskCase
from app.schemas.enums import CaseStatus
from app.services import api_key_service


@pytest.fixture
def auth_test_env():
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
    # Create operator key
    op_key, raw_op_key = api_key_service.create_key(session, name="Agent Scully", scopes=["operator"])
    # Create admin key
    admin_key, raw_admin_key = api_key_service.create_key(session, name="Director Skinner", scopes=["admin"])
    # Create internal key
    internal_key, raw_internal_key = api_key_service.create_key(session, name="Worker Mulder", scopes=["internal"])

    client = TestClient(app)

    yield {
        "client": client,
        "session": session,
        "raw_op_key": raw_op_key,
        "raw_admin_key": raw_admin_key,
        "raw_internal_key": raw_internal_key,
    }

    app.dependency_overrides.clear()
    session.close()


def test_public_routes_accessible_without_auth(auth_test_env):
    client = auth_test_env["client"]
    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_protected_routes_reject_unauthenticated(auth_test_env):
    client = auth_test_env["client"]
    # 401 across protected routers
    assert client.get("/cases").status_code == 401
    assert client.get("/escalations").status_code == 401
    assert client.get("/analytics/recovery").status_code == 401
    assert client.post("/events/", json={}).status_code == 401
    assert client.post("/jobs/verify-promises").status_code == 401
    assert client.post("/simulation/run", json={"seed": 42}).status_code == 401
    assert client.post("/razorpay/create-order", json={"payment_id": "pay_1"}).status_code == 401


def test_scoped_authorization_operator_vs_admin(auth_test_env):
    client = auth_test_env["client"]
    raw_op_key = auth_test_env["raw_op_key"]
    raw_admin_key = auth_test_env["raw_admin_key"]

    op_headers = {"Authorization": f"Bearer {raw_op_key}"}
    admin_headers = {"Authorization": f"Bearer {raw_admin_key}"}

    # Operator can access cases & analytics
    res = client.get("/cases", headers=op_headers)
    assert res.status_code == 200

    res = client.get("/analytics/recovery", headers=op_headers)
    assert res.status_code == 200

    # Operator CANNOT access admin-only endpoints (403 Forbidden)
    res = client.get("/admin/keys", headers=op_headers)
    assert res.status_code == 403

    # Admin CAN access admin endpoints
    res = client.get("/admin/keys", headers=admin_headers)
    assert res.status_code == 200


def test_admin_in_production_guard(auth_test_env):
    client = auth_test_env["client"]
    raw_admin_key = auth_test_env["raw_admin_key"]
    admin_headers = {"Authorization": f"Bearer {raw_admin_key}"}

    # In dev, simulation endpoints pass
    settings.app_env = "dev"
    settings.admin_allowed_in_prod = False
    # Even with empty db it gets past auth
    res = client.get("/admin/keys", headers=admin_headers)
    assert res.status_code == 200

    # In prod, admin simulation/state mutation is strictly blocked
    settings.app_env = "prod"
    settings.admin_allowed_in_prod = False
    res = client.post("/simulation/run", json={"seed": 42}, headers=admin_headers)
    assert res.status_code == 403
    assert "disabled in production" in res.json()["detail"]

    # Explicit override allows it
    settings.admin_allowed_in_prod = True
    res = client.post("/simulation/run", json={"seed": 42}, headers=admin_headers)
    assert res.status_code != 403

    # Reset
    settings.app_env = "dev"
    settings.admin_allowed_in_prod = False


def test_operator_identity_attribution_in_escalations(auth_test_env):
    client = auth_test_env["client"]
    session = auth_test_env["session"]
    raw_op_key = auth_test_env["raw_op_key"]

    # Seed a case and open escalation
    case = RevenueRiskCase(
        id="case_esc_1",
        customer_id="cust_1",
        case_type="FAILED_PAYMENT",
        amount_at_risk=5000.0,
        risk_score=85.0,
        priority="HIGH",
        status=CaseStatus.DETECTED.value,
    )
    esc = Escalation(
        id="esc_test_1",
        case_id=case.id,
        reason="Test high discount request",
        status="OPEN",
    )
    session.add(case)
    session.add(esc)
    session.commit()

    # Assign using operator key, passing the old placeholder "CurrentOperator"
    op_headers = {"Authorization": f"Bearer {raw_op_key}"}
    res = client.post(
        f"/escalations/{esc.id}/assign",
        headers=op_headers,
        json={"owner_id": "CurrentOperator"},
    )
    assert res.status_code == 200
    data = res.json()
    # Verified operator key name "Agent Scully" replaced "CurrentOperator"
    assert data["owner_id"] == "Agent Scully"
