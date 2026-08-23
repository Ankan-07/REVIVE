"""Tests for the deterministic payment-recovery oracle (PRD §28)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
import app.models  # noqa: F401  -- registers every table on Base.metadata for create_all
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.metric import GatewayMetric
from app.schemas.enums import PaymentStatus, InterventionType
from app.simulation.payment_sim import (
    simulate_payment,
    recovery_probability,
    PaymentNotFoundError,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _seed_switch_scenario(db):
    """A payment on a degraded gateway where switching strictly beats retrying.

    intent = 1.0, method_health = 1.0, so p = gateway_health.
      - current gateway PAYU  @ 0.50  -> p_retry  = 0.50
      - best alternative STRIPE @ 0.95 -> p_switch = 0.95
    recovery_roll = 0.70 sits between them: retry fails (0.70 < 0.50 is False),
    switch succeeds (0.70 < 0.95 is True).
    """
    from datetime import datetime
    t = datetime(2026, 1, 1)

    db.add(GatewayMetric(id="GWM-00001", gateway_name="PAYU", success_rate=0.50,
                         baseline_success_rate=0.97, latency_ms=1200.0,
                         health_status="DEGRADED", recorded_at=t))
    db.add(GatewayMetric(id="GWM-00002", gateway_name="STRIPE", success_rate=0.95,
                         baseline_success_rate=0.97, latency_ms=120.0,
                         health_status="HEALTHY", recorded_at=t))
    db.add(GatewayMetric(id="GWM-00003", gateway_name="RAZORPAY", success_rate=0.93,
                         baseline_success_rate=0.96, latency_ms=140.0,
                         health_status="HEALTHY", recorded_at=t))
    db.add(Customer(id="CUS-00001", name="Alice", email="a@example.com",
                    segment="VIP", ltv_amount=5000.0, risk_score=0.1, intent_score=1.0))
    db.add(Payment(id="PAY-00001", customer_id="CUS-00001", amount=999.0, currency="INR",
                   gateway="PAYU", status=PaymentStatus.FAILED.value, error_code="timeout",
                   error_message="Payment failed due to timeout", attempt_count=1,
                   method_health=1.0, recovery_roll=0.70))
    db.commit()


def test_switch_beats_retry(db_session):
    _seed_switch_scenario(db_session)

    retry = simulate_payment(db_session, "PAY-00001", InterventionType.RETRY_PAYMENT.value)
    switch = simulate_payment(db_session, "PAY-00001", InterventionType.SWITCH_GATEWAY.value)

    assert retry["success"] is False
    assert switch["success"] is True

    assert retry["gateway_used"] == "PAYU"
    assert switch["gateway_used"] == "STRIPE"  # healthiest alternative

    assert retry["probability"] == pytest.approx(0.50, abs=1e-6)
    assert switch["probability"] == pytest.approx(0.95, abs=1e-6)


def test_create_payment_link_uses_best_gateway_and_resets_method(db_session):
    _seed_switch_scenario(db_session)

    link = simulate_payment(db_session, "PAY-00001", InterventionType.CREATE_PAYMENT_LINK.value)
    # Best gateway overall is STRIPE @ 0.95; method_health reset to 1.0 -> p = 0.95, roll 0.70 < 0.95.
    assert link["gateway_used"] == "STRIPE"
    assert link["success"] is True
    assert link["signals"]["method_health"] == pytest.approx(1.0, abs=1e-6)


def test_deterministic_and_idempotent(db_session):
    _seed_switch_scenario(db_session)

    calls = [
        simulate_payment(db_session, "PAY-00001", InterventionType.RETRY_PAYMENT.value)
        for _ in range(3)
    ]
    assert calls[0] == calls[1] == calls[2]  # same inputs -> same outcome (§38 idempotency)

    # attempt is echoed but does not change the outcome in this phase.
    a1 = simulate_payment(db_session, "PAY-00001", InterventionType.RETRY_PAYMENT.value, attempt=1)
    a2 = simulate_payment(db_session, "PAY-00001", InterventionType.RETRY_PAYMENT.value, attempt=5)
    assert a1["success"] == a2["success"]
    assert a2["attempt"] == 5


def test_missing_payment_raises(db_session):
    _seed_switch_scenario(db_session)
    with pytest.raises(PaymentNotFoundError):
        simulate_payment(db_session, "PAY-DOES-NOT-EXIST", InterventionType.RETRY_PAYMENT.value)


def test_recovery_probability_formula_and_clamp():
    assert recovery_probability(0.5, 0.8, 1.0) == pytest.approx(0.40, abs=1e-9)
    assert recovery_probability(1.0, 1.0, 1.0) == 1.0
    assert recovery_probability(0.0, 0.9, 0.9) == 0.0
    # clamped to [0, 1] even if inputs are out of range
    assert recovery_probability(2.0, 2.0, 2.0) == 1.0
    assert recovery_probability(-1.0, 0.5, 0.5) == 0.0
