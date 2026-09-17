"""Tests for Phase E3: Sim Alignment.

Validates that:
1. Generator's multi-gateway world is collapsed to Razorpay-only (all payments and gateway metrics).
2. Timeouts are modeled as method-level failures with degraded method_health on Razorpay, not external gateway degradation.
3. Ground-truth projections reflect single-gateway properties (no alternative gateway to switch to; payment link resets method).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
import app.models  # noqa: F401
from app.models.payment import Payment
from app.models.metric import GatewayMetric
from app.simulation import generator
from app.simulation.generator import run_simulation


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_generator_gateways_razorpay_only(db_session):
    """E3: GATEWAYS is strictly ['RAZORPAY'], all generated payments and metrics belong to Razorpay."""
    assert generator.GATEWAYS == ["RAZORPAY"]

    res = run_simulation(db_session, seed=42, customer_count=20, payment_count=60)

    # 1. Gateway snapshots and DB rows are Razorpay-only
    assert len(res["gateways"]) == 1
    assert res["gateways"][0]["gateway"] == "RAZORPAY"
    assert res["gateways"][0]["health_status"] == "HEALTHY"

    metrics = db_session.query(GatewayMetric).all()
    assert len(metrics) == 1
    assert metrics[0].gateway_name == "RAZORPAY"
    assert metrics[0].health_status == "HEALTHY"
    assert metrics[0].baseline_success_rate is not None

    # 2. All generated payments must use RAZORPAY
    payments = db_session.query(Payment).all()
    assert len(payments) == 60
    assert all(p.gateway == "RAZORPAY" for p in payments)


def test_timeout_failures_are_method_level(db_session):
    """E3: Timeouts represent method-level / bank downtime on Razorpay with degraded method_health."""
    run_simulation(db_session, seed=42, customer_count=50, payment_count=500)

    timeouts = db_session.query(Payment).filter(Payment.error_code == "timeout").all()
    assert len(timeouts) > 0, "Expected timeout failures to be generated"

    for p in timeouts:
        assert p.gateway == "RAZORPAY"
        # Method-level degradation: bank/rail timeout degrades instrument health
        assert p.method_health is not None
        assert 0.20 <= p.method_health <= 0.50, (
            f"Expected timeout method_health to be degraded (0.20-0.50), got {p.method_health}"
        )


def test_ground_truth_single_gateway_properties(db_session):
    """E3: Ground-truth math reflects single-gateway realities."""
    res = run_simulation(db_session, seed=42, customer_count=50, payment_count=100)
    gt = res["ground_truth"]

    assert gt["failed"] == res["metrics"]["failed_payments"]
    # With Razorpay as the sole gateway, SWITCH_GATEWAY has no alternative gateway to switch to,
    # so recoverable_by_switch equals recoverable_by_retry.
    assert gt["recoverable_by_switch"] == gt["recoverable_by_retry"]

    # Payment link resets method_health to 1.0, so recoverable_by_link >= recoverable_by_retry
    assert gt["recoverable_by_link"] >= gt["recoverable_by_retry"]
