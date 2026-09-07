import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db import Base
import app.models  # noqa: F401
from app.models.case import RevenueRiskCase
from app.models.customer import Customer
from app.models.escalation import Escalation
from app.models.intervention import Intervention
from app.models.provider_event import ProviderEvent
from app.services import escalation_service, intervention_service


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_idempotency_key_unique_constraint(db_session):
    """A1.2: Database physically rejects duplicate idempotency_key values with IntegrityError."""
    cust = Customer(id="CUS-001", name="Test User", email="test@example.com")
    case = RevenueRiskCase(
        id="RR-001", customer_id="CUS-001", status="OPEN", case_type="FAILED_PAYMENT", amount_at_risk=1000.0
    )
    db_session.add_all([cust, case])
    db_session.commit()

    # First intervention writes cleanly
    i1 = Intervention(
        id="INT-001",
        case_id="RR-001",
        idempotency_key="case-1:retry:1",
        intervention_type="RETRY_PAYMENT",
        status="EXECUTED",
    )
    db_session.add(i1)
    db_session.commit()

    # Second intervention with exact same idempotency_key must raise IntegrityError
    i2 = Intervention(
        id="INT-002",
        case_id="RR-001",
        idempotency_key="case-1:retry:1",
        intervention_type="RETRY_PAYMENT",
        status="EXECUTED",
    )
    db_session.add(i2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_create_executed_handles_concurrent_race(db_session):
    """A1.2: create_executed catches concurrent collision and returns existing row."""
    cust = Customer(id="CUS-002", name="Alice", email="alice@example.com")
    case = RevenueRiskCase(
        id="RR-002", customer_id="CUS-002", status="OPEN", case_type="FAILED_PAYMENT", amount_at_risk=2500.0
    )
    db_session.add_all([cust, case])
    db_session.commit()

    # First creation
    first = intervention_service.create_executed(
        db_session,
        case_id="RR-002",
        action="RETRY_PAYMENT",
        cost=20.0,
        idempotency_key="key-race-test",
        result={"success": True},
    )
    assert first.idempotency_key == "key-race-test"

    # Subsequent call with the exact same key returns the existing row gracefully
    second = intervention_service.create_executed(
        db_session,
        case_id="RR-002",
        action="RETRY_PAYMENT",
        cost=20.0,
        idempotency_key="key-race-test",
        result={"success": True},
    )
    assert second.id == first.id


def test_get_by_idempotency_key_column_and_legacy_fallback(db_session):
    """A1.2: get_by_idempotency_key resolves via column, or falls back to payload_json."""
    cust = Customer(id="CUS-003", name="Bob", email="bob@example.com")
    case = RevenueRiskCase(
        id="RR-003", customer_id="CUS-003", status="OPEN", case_type="FAILED_PAYMENT", amount_at_risk=500.0
    )
    db_session.add_all([cust, case])
    db_session.commit()

    # Legacy row where column is None but payload has the key
    legacy = Intervention(
        id="INT-LEGACY",
        case_id="RR-003",
        idempotency_key=None,
        intervention_type="SEND_REMINDER",
        status="EXECUTED",
        payload_json={"idempotency_key": "legacy-key-123", "sent": True},
    )
    # Modern row with column set
    modern = Intervention(
        id="INT-MODERN",
        case_id="RR-003",
        idempotency_key="modern-key-456",
        intervention_type="CREATE_PAYMENT_LINK",
        status="EXECUTED",
        payload_json={"sent": True},
    )
    db_session.add_all([legacy, modern])
    db_session.commit()

    found_legacy = intervention_service.get_by_idempotency_key(db_session, "RR-003", "legacy-key-123")
    assert found_legacy is not None
    assert found_legacy.id == "INT-LEGACY"

    found_modern = intervention_service.get_by_idempotency_key(db_session, "RR-003", "modern-key-456")
    assert found_modern is not None
    assert found_modern.id == "INT-MODERN"


def test_provider_events_deduplication(db_session):
    """A1.3: provider_events table rejects duplicate razorpay_event_id with IntegrityError."""
    ev1 = ProviderEvent(
        id="PEV-001",
        provider="razorpay",
        razorpay_event_id="evt_test_123456",
        event_type="payment.captured",
        payload_json={"amount": 5000},
        processed=False,
    )
    db_session.add(ev1)
    db_session.commit()

    ev2 = ProviderEvent(
        id="PEV-002",
        provider="razorpay",
        razorpay_event_id="evt_test_123456",  # duplicate event ID
        event_type="payment.captured",
        payload_json={"amount": 5000},
        processed=False,
    )
    db_session.add(ev2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_assign_escalation_with_for_update(db_session):
    """A1.4: assign_escalation executes row lock query without errors."""
    cust = Customer(id="CUS-004", name="Charlie", email="c@example.com")
    case = RevenueRiskCase(
        id="RR-004", customer_id="CUS-004", status="OPEN", case_type="FAILED_PAYMENT", amount_at_risk=3000.0
    )
    esc = Escalation(id="ESC-001", case_id="RR-004", reason="High risk", status="OPEN")
    db_session.add_all([cust, case, esc])
    db_session.commit()

    assigned = escalation_service.assign_escalation(db_session, "ESC-001", "operator-1")
    assert assigned is not None
    assert assigned.owner_id == "operator-1"
