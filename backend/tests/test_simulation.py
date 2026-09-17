import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
import app.models  # noqa: F401  -- registers every table on Base.metadata for create_all
from app.models.customer import Customer
from app.models.order import Order
from app.models.payment import Payment
from app.models.metric import GatewayMetric
from app.simulation.generator import run_simulation


def _fresh_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


@pytest.fixture
def db_session():
    session = _fresh_session()
    try:
        yield session
    finally:
        session.close()


def _snapshot(session):
    """Full ordered snapshot of the generated rows (the fields that must be reproducible)."""
    customers = [
        (c.id, c.name, c.email, c.segment, c.ltv_amount, c.risk_score, c.intent_score)
        for c in session.query(Customer).order_by(Customer.id).all()
    ]
    orders = [
        (o.id, o.customer_id, o.amount, o.status)
        for o in session.query(Order).order_by(Order.id).all()
    ]
    payments = [
        (p.id, p.customer_id, p.order_id, p.amount, p.gateway, p.status,
         p.error_code, p.method_health, p.recovery_roll)
        for p in session.query(Payment).order_by(Payment.id).all()
    ]
    gateways = [
        (g.gateway_name, g.success_rate, g.baseline_success_rate, g.health_status)
        for g in session.query(GatewayMetric).order_by(GatewayMetric.id).all()
    ]
    return customers, orders, payments, gateways


def test_same_seed_reproduces_identical_rows():
    """Phase 2 'done when': the same seed yields byte-identical data (not just equal counts)."""
    s1 = _fresh_session()
    s2 = _fresh_session()
    try:
        run_simulation(s1, seed=42, customer_count=10, payment_count=40)
        run_simulation(s2, seed=42, customer_count=10, payment_count=40)
        assert _snapshot(s1) == _snapshot(s2)
    finally:
        s1.close()
        s2.close()


def test_rerun_on_same_db_appends_without_collision(db_session):
    """Seeding twice into the same DB appends new rows instead of colliding on primary keys."""
    run_simulation(db_session, seed=42, customer_count=10, payment_count=40)
    before_payments = db_session.query(Payment).count()
    before_gateways = db_session.query(GatewayMetric).count()

    res = run_simulation(db_session, seed=7, customer_count=10, payment_count=40)

    assert res["payments_created"] == 40
    assert db_session.query(Payment).count() == before_payments + 40
    assert db_session.query(GatewayMetric).count() == before_gateways + 1

    payment_ids = [r[0] for r in db_session.query(Payment.id).all()]
    assert len(payment_ids) == len(set(payment_ids))  # no duplicate primary keys across runs


def test_different_seed_diverges():
    s1 = _fresh_session()
    s2 = _fresh_session()
    try:
        run_simulation(s1, seed=42, customer_count=10, payment_count=40)
        run_simulation(s2, seed=7, customer_count=10, payment_count=40)
        assert _snapshot(s1) != _snapshot(s2)
    finally:
        s1.close()
        s2.close()


def test_failure_mix_proportions(db_session):
    """Calibrated leak mix (PRD §26): ~5% insufficient_funds, ~3% timeout, ~2% expired_card."""
    n = 1000
    res = run_simulation(db_session, seed=42, customer_count=50, payment_count=n)

    reasons = res["failed_by_reason"]
    total_failed = res["metrics"]["failed_payments"]
    assert total_failed == sum(reasons.values())

    # Rate tolerances (deterministic under seed, but assert bands so RNG-order tweaks don't break it).
    assert abs(reasons["insufficient_funds"] / n - 0.05) < 0.03
    assert abs(reasons["timeout"] / n - 0.03) < 0.03
    assert abs(reasons["expired_card"] / n - 0.02) < 0.03
    assert abs(total_failed / n - 0.10) < 0.04


def test_gateway_health_razorpay_sole_gateway(db_session):
    res = run_simulation(db_session, seed=42, customer_count=10, payment_count=50)

    metrics = db_session.query(GatewayMetric).all()
    assert len(metrics) == 1
    assert metrics[0].gateway_name == "RAZORPAY"
    assert metrics[0].health_status == "HEALTHY"
    assert metrics[0].success_rate > 0.90
    assert metrics[0].baseline_success_rate is not None
    assert len(res["gateways"]) == 1
    assert res["gateways"][0]["gateway"] == "RAZORPAY"


def test_orders_created_and_linked(db_session):
    res = run_simulation(db_session, seed=42, customer_count=10, payment_count=50)

    assert res["orders_created"] == 20  # default = customer_count * 2
    assert db_session.query(Order).count() == 20

    payments = db_session.query(Payment).all()
    linked = [p for p in payments if p.order_id is not None]
    assert len(linked) > 0  # a subset of payments reference an order

    # Every linked order belongs to the same customer as its payment (referential integrity).
    orders_by_id = {o.id: o for o in db_session.query(Order).all()}
    for p in linked:
        assert orders_by_id[p.order_id].customer_id == p.customer_id


def test_ground_truth_consistency(db_session):
    res = run_simulation(db_session, seed=42, customer_count=50, payment_count=1000)
    gt = res["ground_truth"]

    assert gt["failed"] == res["metrics"]["failed_payments"]
    # Recoverability counts can never exceed the number of failures.
    for key in ("recoverable_by_retry", "recoverable_by_switch", "recoverable_by_link"):
        assert 0 <= gt[key] <= gt["failed"]
    assert 0 <= gt["unrecoverable"] <= gt["failed"]
    assert res["amount_at_risk"] >= 0.0


def test_signals_populated_on_rows(db_session):
    run_simulation(db_session, seed=42, customer_count=10, payment_count=50)

    # Every customer has an intent_score in [0, 1].
    for c in db_session.query(Customer).all():
        assert 0.0 <= c.intent_score <= 1.0

    # Every payment carries a method_health in [0, 1] and a stored recovery_roll in [0, 1).
    for p in db_session.query(Payment).all():
        assert 0.0 <= p.method_health <= 1.0
        assert 0.0 <= p.recovery_roll < 1.0

    # expired_card failures have near-dead method health (retry/switch can't fix them).
    expired = db_session.query(Payment).filter(Payment.error_code == "expired_card").all()
    assert all(p.method_health <= 0.10 for p in expired)
