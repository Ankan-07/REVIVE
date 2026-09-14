"""Tests for Phase B3: Server-Side Settlement Confirmation (closing the trust gap).

Asserts:
- Callback with valid HMAC but uncaptured/mismatched payment does NOT settle.
- Currency mismatch (non-INR) is rejected.
- Order ID mismatch is rejected.
- Underpaid amount (< expected) is rejected.
- Actual gateway fee (fee in paise) is booked into provider_objects and RecoveryOutcome.
- Deterministic net recovery formula: net = gross - cost - discount - gateway_fee.
- Partial recovery sets outcome_type to RECOVERED_PARTIAL.
- update_ledger node respects actual settled amount and gateway fees.
"""
from __future__ import annotations

import hashlib
import hmac
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
import app.models  # noqa: F401
from app.models.case import RevenueRiskCase
from app.models.customer import Customer
from app.models.outcome import RecoveryOutcome
from app.models.payment import Payment
from app.models.provider_object import ProviderObject
from app.schemas.enums import CaseStatus, OutcomeType, PaymentStatus
from app.services import intervention_service, provider_object_service, razorpay_service
from app.services.razorpay_service import PaymentVerificationError
from app.agent.nodes.update_ledger import update_ledger

KEY_ID = "rzp_test_b3testkey123"
KEY_SECRET = "test_secret_b312345"


def _sign(order_id: str, payment_id: str, secret: str = KEY_SECRET) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        f"{order_id}|{payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@pytest.fixture
def db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    monkeypatch.setenv("RAZORPAY_KEY_ID", KEY_ID)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", KEY_SECRET)

    try:
        yield session
    finally:
        session.close()


def _seed(db: sessionmaker, *, amount: float = 5000.0, amount_at_risk: float = 5000.0):
    cust = Customer(id="CUS-B3", name="Bob", email="bob@example.com")
    pay = Payment(
        id="PAY-B3",
        customer_id="CUS-B3",
        amount=amount,
        currency="INR",
        gateway="RAZORPAY",
        status=PaymentStatus.FAILED.value,
        recovery_roll=0.5,
    )
    case = RevenueRiskCase(
        id="RR-B3",
        customer_id="CUS-B3",
        payment_id="PAY-B3",
        case_type="FAILED_PAYMENT",
        status=CaseStatus.DETECTED.value,
        amount_at_risk=amount_at_risk,
    )
    db.add_all([cust, pay, case])
    db.commit()


def test_uncaptured_payment_refuses_settle(db, monkeypatch):
    """B3.1: Valid signature but payment status is authorized (not captured) must fail."""
    _seed(db)
    sig = _sign("order_123", "pay_uncaptured")

    # Gateway returns authorized (not captured)
    monkeypatch.setattr(
        razorpay_service,
        "_fetch_payment_on_gateway",
        lambda pid: {
            "id": pid,
            "order_id": "order_123",
            "amount": 500000,
            "currency": "INR",
            "status": "authorized",
            "captured": False,
            "fee": 0,
        },
    )

    with pytest.raises(PaymentVerificationError) as exc_info:
        razorpay_service.verify_and_settle(
            db,
            payment_id="PAY-B3",
            order_id="order_123",
            razorpay_payment_id="pay_uncaptured",
            razorpay_signature=sig,
        )

    assert "not captured on gateway" in str(exc_info.value)

    # Verify state did NOT change
    db.expire_all()
    pay = db.query(Payment).filter(Payment.id == "PAY-B3").first()
    assert pay.status == PaymentStatus.FAILED.value
    assert db.query(RecoveryOutcome).count() == 0


def test_mismatched_currency_refuses_settle(db, monkeypatch):
    """B3.1: Valid signature but currency is USD instead of INR must fail."""
    _seed(db)
    sig = _sign("order_123", "pay_usd")

    monkeypatch.setattr(
        razorpay_service,
        "_fetch_payment_on_gateway",
        lambda pid: {
            "id": pid,
            "order_id": "order_123",
            "amount": 500000,
            "currency": "USD",
            "status": "captured",
            "captured": True,
            "fee": 1000,
        },
    )

    with pytest.raises(PaymentVerificationError) as exc_info:
        razorpay_service.verify_and_settle(
            db,
            payment_id="PAY-B3",
            order_id="order_123",
            razorpay_payment_id="pay_usd",
            razorpay_signature=sig,
        )

    assert "currency 'USD' does not match expected INR" in str(exc_info.value)
    db.expire_all()
    pay = db.query(Payment).filter(Payment.id == "PAY-B3").first()
    assert pay.status == PaymentStatus.FAILED.value


def test_mismatched_order_id_refuses_settle(db, monkeypatch):
    """B3.1: Gateway payment belongs to a different order -> must fail."""
    _seed(db)
    sig = _sign("order_123", "pay_wrong_order")

    monkeypatch.setattr(
        razorpay_service,
        "_fetch_payment_on_gateway",
        lambda pid: {
            "id": pid,
            "order_id": "order_attacker_999",
            "amount": 500000,
            "currency": "INR",
            "status": "captured",
            "captured": True,
            "fee": 1000,
        },
    )

    with pytest.raises(PaymentVerificationError) as exc_info:
        razorpay_service.verify_and_settle(
            db,
            payment_id="PAY-B3",
            order_id="order_123",
            razorpay_payment_id="pay_wrong_order",
            razorpay_signature=sig,
        )

    assert "order_attacker_999" in str(exc_info.value)
    db.expire_all()
    pay = db.query(Payment).filter(Payment.id == "PAY-B3").first()
    assert pay.status == PaymentStatus.FAILED.value


def test_order_bound_to_different_case_refuses_settle(db, monkeypatch):
    """B3.1: Order in provider_objects belongs to a different case -> must fail."""
    _seed(db)
    # Register order_123 to RR-OTHER
    provider_object_service.record_object(
        db,
        case_id="RR-OTHER",
        object_type="order",
        provider_object_id="order_123",
        amount_paise=500000,
        status="created",
    )

    sig = _sign("order_123", "pay_123")
    monkeypatch.setattr(
        razorpay_service,
        "_fetch_payment_on_gateway",
        lambda pid: {
            "id": pid,
            "order_id": "order_123",
            "amount": 500000,
            "currency": "INR",
            "status": "captured",
            "captured": True,
            "fee": 1000,
        },
    )

    with pytest.raises(PaymentVerificationError) as exc_info:
        razorpay_service.verify_and_settle(
            db,
            payment_id="PAY-B3",
            order_id="order_123",
            razorpay_payment_id="pay_123",
            razorpay_signature=sig,
        )

    assert "bound to case RR-OTHER" in str(exc_info.value)


def test_underpaid_amount_refuses_settle(db, monkeypatch):
    """B3.1: Payment amount is less than expected payment amount -> must fail."""
    _seed(db, amount=5000.0)  # expects 500000 paise
    sig = _sign("order_123", "pay_underpaid")

    monkeypatch.setattr(
        razorpay_service,
        "_fetch_payment_on_gateway",
        lambda pid: {
            "id": pid,
            "order_id": "order_123",
            "amount": 10000,  # only ₹100.00
            "currency": "INR",
            "status": "captured",
            "captured": True,
            "fee": 200,
        },
    )

    with pytest.raises(PaymentVerificationError) as exc_info:
        razorpay_service.verify_and_settle(
            db,
            payment_id="PAY-B3",
            order_id="order_123",
            razorpay_payment_id="pay_underpaid",
            razorpay_signature=sig,
        )

    assert "amount 10000 paise is less than expected 500000 paise" in str(exc_info.value)
    db.expire_all()
    pay = db.query(Payment).filter(Payment.id == "PAY-B3").first()
    assert pay.status == PaymentStatus.FAILED.value


def test_successful_settlement_records_fee_and_computes_net(db, monkeypatch):
    """B3.2 & B3.3: Capture fee is booked, subtracted from net recovery, and saved in provider_objects."""
    _seed(db, amount=5000.0, amount_at_risk=5000.0)
    # Seed intervention cost of ₹25.0
    intervention_service.create_executed(
        db,
        case_id="RR-B3",
        action="RETRY_PAYMENT",
        cost=25.0,
        idempotency_key="RR-B3:retry:1",
        result={"success": False},
    )

    sig = _sign("order_good", "pay_good")
    # Gateway fee: 11800 paise = ₹118.00
    monkeypatch.setattr(
        razorpay_service,
        "_fetch_payment_on_gateway",
        lambda pid: {
            "id": pid,
            "order_id": "order_good",
            "amount": 500000,
            "currency": "INR",
            "status": "captured",
            "captured": True,
            "fee": 11800,
        },
    )

    res = razorpay_service.verify_and_settle(
        db,
        payment_id="PAY-B3",
        order_id="order_good",
        razorpay_payment_id="pay_good",
        razorpay_signature=sig,
    )

    assert res["status"] == "success"
    # Net = 5000.0 gross - 25.0 cost - 0.0 discount - 118.0 fee = 4857.0
    assert res["net_recovered"] == pytest.approx(4857.0)

    db.expire_all()
    # Check outcome table
    outcome = db.query(RecoveryOutcome).filter(RecoveryOutcome.case_id == "RR-B3").first()
    assert outcome is not None
    assert outcome.outcome_type == OutcomeType.RECOVERED_FULL.value
    assert outcome.gross_recovered == pytest.approx(5000.0)
    assert outcome.gateway_fee_paise == 11800
    assert outcome.gateway_fee == pytest.approx(118.0)
    assert outcome.net_recovered == pytest.approx(4857.0)

    # Check case
    case = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == "RR-B3").first()
    assert case.status == CaseStatus.RECOVERED.value
    assert case.net_recovered_amount == pytest.approx(4857.0)

    # Check provider_objects
    pay_obj = db.query(ProviderObject).filter(ProviderObject.provider_object_id == "pay_good").first()
    assert pay_obj is not None
    assert pay_obj.status == "captured"
    assert pay_obj.amount_paise == 500000
    assert pay_obj.fee_paise == 11800


def test_partial_recovery_sets_recovered_partial_outcome(db, monkeypatch):
    """B3.2: When settled gross is less than amount at risk, record RECOVERED_PARTIAL."""
    # Case amount at risk is ₹10,000.0, payment is ₹6,000.0
    _seed(db, amount=6000.0, amount_at_risk=10000.0)

    sig = _sign("order_partial", "pay_partial")
    monkeypatch.setattr(
        razorpay_service,
        "_fetch_payment_on_gateway",
        lambda pid: {
            "id": pid,
            "order_id": "order_partial",
            "amount": 600000,
            "currency": "INR",
            "status": "captured",
            "captured": True,
            "fee": 14160,  # ₹141.60
        },
    )

    res = razorpay_service.verify_and_settle(
        db,
        payment_id="PAY-B3",
        order_id="order_partial",
        razorpay_payment_id="pay_partial",
        razorpay_signature=sig,
    )
    assert res["status"] == "success"

    db.expire_all()
    outcome = db.query(RecoveryOutcome).filter(RecoveryOutcome.case_id == "RR-B3").first()
    assert outcome is not None
    assert outcome.outcome_type == OutcomeType.RECOVERED_PARTIAL.value
    assert outcome.gross_recovered == pytest.approx(6000.0)
    assert outcome.gateway_fee_paise == 14160
    assert outcome.net_recovered == pytest.approx(6000.0 - 141.60)


def test_update_ledger_with_settled_amount_and_fee(db):
    """B3.2 & B3.3: update_ledger books actual gross and gateway fee correctly."""
    _seed(db, amount=10000.0, amount_at_risk=10000.0)

    state = {
        "case_id": "RR-B3",
        "terminal_status": "RECOVERED",
        "settled_amount": 7500.0,
        "gateway_fee_paise": 17700,  # ₹177.00
    }
    config = {"configurable": {"session_factory": lambda: db}}

    update_ledger(state, config)

    db.expire_all()
    outcome = db.query(RecoveryOutcome).filter(RecoveryOutcome.case_id == "RR-B3").first()
    assert outcome is not None
    assert outcome.outcome_type == OutcomeType.RECOVERED_PARTIAL.value
    assert outcome.gross_recovered == pytest.approx(7500.0)
    assert outcome.gateway_fee_paise == 17700
    assert outcome.gateway_fee == pytest.approx(177.0)
    assert outcome.net_recovered == pytest.approx(7500.0 - 177.0)
