"""Tests for the failed-payment detector (Phase 3 seam).

The detector emits real `POST /events/` calls. We exercise the true ASGI route in-process with a
FastAPI `TestClient` (no live server) and route the nested handler to the same in-memory DB via a
`get_db` dependency override. `StaticPool` keeps the one in-memory connection shared across the
TestClient's worker thread.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.db import Base, get_db
import app.models  # noqa: F401  -- registers every table on Base.metadata for create_all
from app.main import app
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.metric import GatewayMetric
from app.models.case import RevenueRiskCase
from app.models.audit import AuditEvent
from app.schemas.enums import PaymentStatus
from app.services.detector import emit_failed_payment_events


@pytest.fixture
def session_and_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared connection -> nested /events/ handler sees the same DB
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    try:
        yield session, client
    finally:
        app.dependency_overrides.clear()
        session.close()


def _seed(session):
    """Two FAILED payments (on different gateways) + one SUCCEEDED payment."""
    session.add_all(
        [
            GatewayMetric(id="GWM-1", gateway_name="STRIPE", success_rate=0.96,
                          baseline_success_rate=0.97, latency_ms=120.0, health_status="HEALTHY"),
            GatewayMetric(id="GWM-2", gateway_name="RAZORPAY", success_rate=0.95,
                          baseline_success_rate=0.96, latency_ms=140.0, health_status="HEALTHY"),
            GatewayMetric(id="GWM-3", gateway_name="PAYU", success_rate=0.70,
                          baseline_success_rate=0.97, latency_ms=1200.0, health_status="DEGRADED"),
        ]
    )
    session.add(Customer(id="CUS-1", name="A", email="a@x.com", segment="VIP",
                         ltv_amount=6000.0, risk_score=0.2, intent_score=0.9))
    session.add(Customer(id="CUS-2", name="B", email="b@x.com", segment="STANDARD",
                         ltv_amount=1000.0, risk_score=0.3, intent_score=0.7))
    session.add(Payment(id="PAY-1", customer_id="CUS-1", amount=1500.0, currency="INR",
                        gateway="PAYU", status=PaymentStatus.FAILED.value, error_code="timeout",
                        method_health=0.9, recovery_roll=0.3))
    session.add(Payment(id="PAY-2", customer_id="CUS-2", amount=800.0, currency="INR",
                        gateway="STRIPE", status=PaymentStatus.FAILED.value,
                        error_code="insufficient_funds", method_health=0.4, recovery_roll=0.5))
    session.add(Payment(id="PAY-3", customer_id="CUS-1", amount=999.0, currency="INR",
                        gateway="STRIPE", status=PaymentStatus.SUCCEEDED.value, error_code=None,
                        method_health=1.0, recovery_roll=0.1))
    session.commit()


def test_detector_creates_one_case_per_failed_payment(session_and_client):
    session, client = session_and_client
    _seed(session)

    summary = emit_failed_payment_events(session, client)

    assert summary["scanned"] == 2  # only the two FAILED payments
    assert summary["cases_created"] == 2
    assert summary["already_cased"] == 0
    assert summary["errors"] == 0

    cases = session.query(RevenueRiskCase).all()
    assert len(cases) == 2
    assert {c.payment_id for c in cases} == {"PAY-1", "PAY-2"}  # the SUCCEEDED payment is not cased

    for c in cases:
        assert c.payment_id is not None
        assert c.recovery_probability is not None
        assert 0.0 <= c.recovery_probability <= 1.0
        assert c.status == "DETECTED"

    # One CASE_CREATED audit row per case.
    assert session.query(AuditEvent).filter(AuditEvent.event_type == "CASE_CREATED").count() == 2


def test_detector_is_idempotent(session_and_client):
    session, client = session_and_client
    _seed(session)

    first = emit_failed_payment_events(session, client)
    assert first["cases_created"] == 2

    # Re-running finds no uncased failures -> nothing scanned, no duplicates created.
    second = emit_failed_payment_events(session, client)
    assert second["scanned"] == 0
    assert second["cases_created"] == 0
    assert session.query(RevenueRiskCase).count() == 2


def test_detector_went_through_the_real_events_route(session_and_client):
    """Each emission is a genuine POST /events/ returning the handler's success envelope."""
    session, client = session_and_client
    _seed(session)

    summary = emit_failed_payment_events(session, client)

    assert len(summary["results"]) == 2
    for r in summary["results"]:
        assert r["status_code"] == 200
        assert r["body"]["status"] == "success"
        assert r["body"]["case_id"].startswith("case_")
        assert r["body"]["audit_id"].startswith("aud_")
