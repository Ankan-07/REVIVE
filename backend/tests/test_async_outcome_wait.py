"""Tests for Phase B4: Async Outcome Wait, LangGraph parking, and Webhook/Timeout Resumption."""
import os
import tempfile
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent.runner import run_agent, resume_agent_outcome
from app.config import settings
from app.db import Base
from app.models.audit import AuditEvent
from app.models.case import RevenueRiskCase
from app.models.customer import Customer
from app.models.payment import Payment
from app.schemas.enums import CaseStatus, CaseType, PaymentStatus
from app.services import provider_event_service


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db(factory):
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def checkpointer():
    return MemorySaver()


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    """Force hermetic test environment."""
    for var in ("OPENAI_API_KEY", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def _seed_live_case(db, case_id="RR-LIVE-B4", amount=2000.0):
    cust = Customer(
        id=f"CUS-{case_id}",
        name="Test Customer B4",
        email="customer@example.com",
        phone="+919876543210",
        origin="live",
    )
    pay = Payment(
        id=f"PAY-{case_id}",
        customer_id=cust.id,
        amount=amount,
        currency="INR",
        status=PaymentStatus.FAILED.value,
        gateway="RAZORPAY",
        origin="live",
    )
    case = RevenueRiskCase(
        id=case_id,
        customer_id=cust.id,
        payment_id=pay.id,
        case_type=CaseType.FAILED_PAYMENT.value,
        origin="live",
        status=CaseStatus.DETECTED.value,
        amount_at_risk=amount,
        priority="MEDIUM",
    )
    db.add(cust)
    db.add(pay)
    db.add(case)
    db.commit()
    return case


def test_live_case_parks_at_waiting_for_outcome(factory, db, checkpointer, monkeypatch):
    """Verify that a live case executing a payment action parks at WAITING_FOR_OUTCOME."""
    monkeypatch.setattr(settings, "live_recovery_enabled", True)
    case = _seed_live_case(db, "RR-PARK-1", amount=1500.0)

    # Mock payment link tool in live tool registry
    monkeypatch.setattr(
        "app.services.razorpay_service.create_payment_link_for_case",
        lambda *args, **kwargs: {
            "id": "plink_test_123",
            "short_url": "https://rzp.io/i/test123",
            "status": "created",
            "amount": 150000,
        },
    )

    result = run_agent(case.id, session_factory=factory, checkpointer=checkpointer)

    # Execution paused before outcome_pause: terminal_status should be None
    assert result.get("terminal_status") is None
    assert result.get("await_outcome") is True

    # Database state must be WAITING_FOR_OUTCOME
    db.expire_all()
    fresh_case = db.query(RevenueRiskCase).filter_by(id=case.id).first()
    assert fresh_case.status == CaseStatus.WAITING_FOR_OUTCOME.value

    # Audit events must show TOOL_EXECUTED and WAITING_FOR_OUTCOME
    events = [
        a.event_type for a in db.query(AuditEvent).filter_by(case_id=case.id).order_by(AuditEvent.id).all()
    ]
    assert "TOOL_EXECUTED" in events
    assert "WAITING_FOR_OUTCOME" in events


def test_resume_parked_case_with_payment_outcome(factory, db, checkpointer, monkeypatch):
    """Verify that resume_agent_outcome unparks the graph and drives it to RECOVERED."""
    monkeypatch.setattr(settings, "live_recovery_enabled", True)
    case = _seed_live_case(db, "RR-PARK-2", amount=3000.0)

    monkeypatch.setattr(
        "app.services.razorpay_service.create_payment_link_for_case",
        lambda *args, **kwargs: {
            "id": "plink_test_456",
            "short_url": "https://rzp.io/i/test456",
            "status": "created",
            "amount": 300000,
        },
    )

    # Park the run
    run_agent(case.id, session_factory=factory, checkpointer=checkpointer)

    # Resume the run via outcome
    res = resume_agent_outcome(
        case.id,
        {
            "recovered": True,
            "gross_recovered": 3000.0,
            "net_recovered": 2940.0,
            "gateway_fee_paise": 6000,
            "verified_via": "razorpay_webhook",
        },
        session_factory=factory,
        checkpointer=checkpointer,
        caller="webhook",
    )

    assert res.get("terminal_status") == "RECOVERED"

    db.expire_all()
    fresh_case = db.query(RevenueRiskCase).filter_by(id=case.id).first()
    assert fresh_case.status == CaseStatus.RECOVERED.value

    # Verify audit trail contains OUTCOME_OBSERVED and RECOVERED
    events = [
        a.event_type for a in db.query(AuditEvent).filter_by(case_id=case.id).order_by(AuditEvent.id).all()
    ]
    assert "OUTCOME_OBSERVED" in events
    assert "RECOVERED" in events


def test_webhook_event_resumes_parked_case(factory, db, checkpointer, monkeypatch):
    """Verify that a payment.captured webhook automatically resumes a parked graph."""
    monkeypatch.setattr(settings, "live_recovery_enabled", True)
    monkeypatch.setattr("app.agent.runner._default_checkpointer", lambda: checkpointer)
    case = _seed_live_case(db, "RR-PARK-WEBHOOK", amount=2500.0)

    monkeypatch.setattr(
        "app.services.razorpay_service.create_payment_link_for_case",
        lambda *args, **kwargs: {
            "payment_link_id": "plink_webhook_789",
            "id": "plink_webhook_789",
            "short_url": "https://rzp.io/i/webhook789",
            "status": "created",
            "amount": 250000,
        },
    )

    # 1. Park run
    run_agent(case.id, session_factory=factory, checkpointer=checkpointer)
    db.expire_all()
    assert db.query(RevenueRiskCase).filter_by(id=case.id).first().status == CaseStatus.WAITING_FOR_OUTCOME.value

    # 2. Record provider_objects link to bind order/payment to case
    from app.services import provider_object_service
    provider_object_service.record_object(
        db,
        case_id=case.id,
        object_type="payment_link",
        provider_object_id="plink_webhook_789",
        amount_paise=250000,
        status="created",
    )

    # 3. Simulate webhook event for payment.captured
    event_payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_live_webhook_01",
                    "amount": 250000,
                    "currency": "INR",
                    "fee": 5000,
                }
            },
            "payment_link": {
                "entity": {
                    "id": "plink_webhook_789",
                    "amount": 250000,
                    "status": "paid",
                }
            },
        },
    }
    event_pk, is_new, _ = provider_event_service.record_raw_event(
        db,
        provider="razorpay",
        razorpay_event_id="evt_test_b4_capture",
        event_type="payment.captured",
        payload_json=event_payload,
    )

    # Process event
    res = provider_event_service.process_provider_event(db, event_id=event_pk)
    assert res["status"] == "processed"

    db.expire_all()
    fresh_case = db.query(RevenueRiskCase).filter_by(id=case.id).first()
    assert fresh_case.status == CaseStatus.RECOVERED.value


def test_outcome_expiry_timeout(factory, db, checkpointer, monkeypatch):
    """Verify that outcome expiration / timeout resumes the graph and triggers router decision."""
    monkeypatch.setattr(settings, "live_recovery_enabled", True)
    case = _seed_live_case(db, "RR-TIMEOUT", amount=1200.0)

    monkeypatch.setattr(
        "app.services.razorpay_service.create_payment_link_for_case",
        lambda *args, **kwargs: {
            "id": "plink_test_timeout",
            "short_url": "https://rzp.io/i/timeout",
            "status": "created",
            "amount": 120000,
        },
    )

    run_agent(case.id, session_factory=factory, checkpointer=checkpointer)

    # Resume with expired outcome
    res = resume_agent_outcome(
        case.id,
        {
            "recovered": False,
            "expired": True,
            "reason": "timeout",
            "verified_via": "outcome_wait_timeout",
        },
        session_factory=factory,
        checkpointer=checkpointer,
        caller="timeout_worker",
    )

    # Outcome observed as False, so router either continues or stops if budget exhausted
    assert res.get("outcome", {}).get("recovered") is False
    assert "ROUTER_DECISION" in [
        a.event_type for a in db.query(AuditEvent).filter_by(case_id=case.id).all()
    ]


def test_park_resume_survives_process_restart(factory, db, monkeypatch):
    """Verify that a parked run survives checkpointer re-instantiation (simulating process restart)."""
    monkeypatch.setattr(settings, "live_recovery_enabled", True)
    case = _seed_live_case(db, "RR-RESTART-DURABLE", amount=4000.0)

    monkeypatch.setattr(
        "app.services.razorpay_service.create_payment_link_for_case",
        lambda *args, **kwargs: {
            "id": "plink_durable_1",
            "short_url": "https://rzp.io/i/durable1",
            "status": "created",
            "amount": 400000,
        },
    )

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        sqlite_path = tf.name

    try:
        import sqlite3
        conn1 = sqlite3.connect(sqlite_path, check_same_thread=False)
        saver1 = SqliteSaver(conn1)
        saver1.setup()

        # Run 1: Parks at outcome_pause
        res1 = run_agent(case.id, session_factory=factory, checkpointer=saver1)
        assert res1.get("await_outcome") is True
        conn1.close()

        # Simulate fresh process boot: open brand new connection to the same SQLite DB
        conn2 = sqlite3.connect(sqlite_path, check_same_thread=False)
        saver2 = SqliteSaver(conn2)

        # Run 2: Resume from checkpoint
        res2 = resume_agent_outcome(
            case.id,
            {
                "recovered": True,
                "gross_recovered": 4000.0,
                "net_recovered": 3920.0,
                "gateway_fee_paise": 8000,
                "verified_via": "razorpay_webhook",
            },
            session_factory=factory,
            checkpointer=saver2,
        )

        assert res2.get("terminal_status") == "RECOVERED"
        conn2.close()
    finally:
        if os.path.exists(sqlite_path):
            os.remove(sqlite_path)
