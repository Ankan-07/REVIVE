"""Tests for the Razorpay Standard Checkout integration.

Hermetic by design:
* The real gateway boundary (``razorpay_service._create_order_on_gateway``) is monkeypatched
  so no network call is ever made.
* Signature verification is local HMAC math — no SDK call.
* An autouse fixture blanks the Razorpay env keys so a developer's local ``.env`` can never
  make a test hit the network; tests that need the real path set the keys explicitly.
"""
from __future__ import annotations

import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
import app.models  # noqa: F401  -- registers every table on Base.metadata for create_all
from app.main import app
from app.models.audit import AuditEvent
from app.models.case import RevenueRiskCase
from app.models.customer import Customer
from app.models.intervention import Intervention
from app.models.outcome import RecoveryOutcome
from app.models.payment import Payment
from app.schemas.enums import CaseStatus, PaymentStatus
from app.services import intervention_service
from app.services import razorpay_service

KEY_ID = "rzp_test_111111111111"
KEY_SECRET = "test_secret_1234567890"


def _sign(order_id: str, payment_id: str, secret: str = KEY_SECRET) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        f"{order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@pytest.fixture(autouse=True)
def _hermetic_razorpay_env(monkeypatch):
    """Never let a local .env leak Razorpay keys into the test suite."""
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)


@pytest.fixture
def session_and_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    monkeypatch.setenv("RAZORPAY_KEY_ID", KEY_ID)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", KEY_SECRET)

    app.dependency_overrides[get_db] = lambda: session
    try:
        yield session, TestClient(app)
    finally:
        app.dependency_overrides.clear()
        session.close()


def _seed(db, *, status=PaymentStatus.FAILED.value, case_status=CaseStatus.DETECTED.value):
    db.add(Customer(id="CUS-00001", name="Alice", email="a@example.com", segment="VIP",
                    ltv_amount=8000.0, risk_score=0.2, intent_score=0.9))
    db.add(Payment(id="PAY-00001", customer_id="CUS-00001", amount=5000.0, currency="INR",
                   gateway="RAZORPAY", status=status, error_code="timeout",
                   error_message="Payment failed due to timeout",
                   attempt_count=1, method_health=1.0, recovery_roll=0.5))
    if case_status:
        db.add(RevenueRiskCase(id="RR-00001", customer_id="CUS-00001", payment_id="PAY-00001",
                               case_type="FAILED_PAYMENT", status=case_status,
                               amount_at_risk=5000.0, priority="HIGH", risk_score=0.6))
    db.commit()


def _seed_intervention_cost(db, case_id="RR-00001", cost=20.0):
    """One prior agent intervention so the ledger has real costs to subtract."""
    intervention_service.create_executed(
        db,
        case_id=case_id,
        action="RETRY_PAYMENT",
        cost=cost,
        idempotency_key=f"{case_id}:RETRY_PAYMENT:1",
        result={"success": False, "error_code": "timeout"},
    )


# --------------------------------------------------------------------------------------------------
# create-order
# --------------------------------------------------------------------------------------------------
def test_create_order_returns_razorpay_order(session_and_client, monkeypatch):
    session, client = session_and_client
    _seed(session)

    def fake_create(amount_paise, receipt, notes):
        assert amount_paise == 500000  # ₹5000 -> paise
        assert receipt == "PAY-00001"
        return {"id": "order_O1test123", "amount": amount_paise, "currency": "INR"}

    monkeypatch.setattr(razorpay_service, "_create_order_on_gateway", fake_create)

    resp = client.post("/razorpay/create-order", json={"payment_id": "PAY-00001"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["order_id"] == "order_O1test123"
    assert body["payment_id"] == "PAY-00001"
    assert body["case_id"] == "RR-00001"
    assert body["amount_paise"] == 500000
    assert body["currency"] == "INR"

    # The payment row is untouched until verification.
    session.expire_all()
    payment = session.query(Payment).filter(Payment.id == "PAY-00001").first()
    assert payment.status == PaymentStatus.FAILED.value

    # Order creation is audited.
    kinds = [e.event_type for e in session.query(AuditEvent).all()]
    assert "PAYMENT_ORDER_CREATED" in kinds


def test_create_order_requires_configuration(session_and_client, monkeypatch):
    session, client = session_and_client
    _seed(session)
    monkeypatch.delenv("RAZORPAY_KEY_ID")
    monkeypatch.delenv("RAZORPAY_KEY_SECRET")

    resp = client.post("/razorpay/create-order", json={"payment_id": "PAY-00001"})
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()


def test_create_order_unknown_payment_404(session_and_client):
    session, client = session_and_client
    _seed(session)

    resp = client.post("/razorpay/create-order", json={"payment_id": "PAY-99999"})
    assert resp.status_code == 404


def test_create_order_refuses_already_succeeded_payment(session_and_client):
    session, client = session_and_client
    _seed(session, status=PaymentStatus.SUCCEEDED.value, case_status=CaseStatus.RECOVERED.value)

    resp = client.post("/razorpay/create-order", json={"payment_id": "PAY-00001"})
    assert resp.status_code == 409
    assert "already SUCCEEDED" in resp.json()["detail"]


# --------------------------------------------------------------------------------------------------
# verify-payment
# --------------------------------------------------------------------------------------------------
def test_verify_wrong_signature_is_rejected_and_not_settled(session_and_client):
    session, client = session_and_client
    _seed(session)
    _seed_intervention_cost(session)

    resp = client.post(
        "/razorpay/verify-payment",
        json={
            "payment_id": "PAY-00001",
            "razorpay_order_id": "order_O1test123",
            "razorpay_payment_id": "pay_O2test123",
            "razorpay_signature": "deadbeef" * 8,  # garbage
        },
    )

    assert resp.status_code == 400
    session.expire_all()
    payment = session.query(Payment).filter(Payment.id == "PAY-00001").first()
    assert payment.status == PaymentStatus.FAILED.value  # never marked paid
    assert session.query(RecoveryOutcome).count() == 0
    case = session.query(RevenueRiskCase).filter(RevenueRiskCase.id == "RR-00001").first()
    assert case.status == CaseStatus.DETECTED.value


def test_verify_valid_signature_settles_payment_and_closes_case(session_and_client):
    session, client = session_and_client
    _seed(session)
    _seed_intervention_cost(session, cost=20.0)  # net = 5000 - 20 = 4980

    signature = _sign("order_O1test123", "pay_O2test123")

    resp = client.post(
        "/razorpay/verify-payment",
        json={
            "payment_id": "PAY-00001",
            "razorpay_order_id": "order_O1test123",
            "razorpay_payment_id": "pay_O2test123",
            "razorpay_signature": signature,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    assert body["net_recovered"] == pytest.approx(4980.0)

    session.expire_all()
    payment = session.query(Payment).filter(Payment.id == "PAY-00001").first()
    assert payment.status == PaymentStatus.SUCCEEDED.value
    assert payment.error_code is None

    case = session.query(RevenueRiskCase).filter(RevenueRiskCase.id == "RR-00001").first()
    assert case.status == CaseStatus.RECOVERED.value
    assert case.net_recovered_amount == pytest.approx(4980.0)

    outcomes = session.query(RecoveryOutcome).filter(RecoveryOutcome.case_id == "RR-00001").all()
    assert len(outcomes) == 1
    assert outcomes[0].outcome_type == "RECOVERED_FULL"
    assert outcomes[0].gross_recovered == pytest.approx(5000.0)

    event_types = [e.event_type for e in session.query(AuditEvent).all()]
    assert "PAYMENT_VERIFIED" in event_types or "RECOVERED" in event_types


def test_verify_is_idempotent_no_double_settle(session_and_client):
    session, client = session_and_client
    _seed(session)
    _seed_intervention_cost(session)

    signature = _sign("order_O1test123", "pay_O2test123")
    payload = {
        "payment_id": "PAY-00001",
        "razorpay_order_id": "order_O1test123",
        "razorpay_payment_id": "pay_O2test123",
        "razorpay_signature": signature,
    }

    first = client.post("/razorpay/verify-payment", json=payload)
    assert first.status_code == 200 and first.json()["status"] == "success"

    second = client.post("/razorpay/verify-payment", json=payload)
    assert second.status_code == 200
    assert second.json()["status"] == "already_paid"

    assert session.query(RecoveryOutcome).count() == 1  # no second ledger row
    assert session.query(Intervention).count() == 1
