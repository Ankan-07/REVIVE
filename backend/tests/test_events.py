import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.schemas.events import EventPayload
from app.schemas.enums import EventType
from app.services.event_service import handle_event
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.case import RevenueRiskCase
from app.models.audit import AuditEvent


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_handle_payment_failed_event(db_session):
    # Setup Customer and Payment
    cust = Customer(id="cust_1", name="Test", email="test@test.com", risk_score=0.2, ltv_amount=6000)
    db_session.add(cust)
    db_session.commit()

    pay = Payment(id="pay_1", customer_id="cust_1", amount=1500, gateway="STRIPE", status="FAILED")
    db_session.add(pay)
    db_session.commit()

    event = EventPayload(
        event_type=EventType.PAYMENT_FAILED,
        customer_id="cust_1",
        payment_id="pay_1",
        amount=1500
    )

    res = handle_event(db_session, event)

    assert res["status"] == "success"
    assert "case_id" in res
    assert "audit_id" in res

    # Verify case created
    case = db_session.query(RevenueRiskCase).filter(RevenueRiskCase.id == res["case_id"]).first()
    assert case is not None
    assert case.customer_id == "cust_1"
    assert case.amount_at_risk == 1500
    assert case.priority == "HIGH"
    assert case.status == "DETECTED"
    assert case.payment_id == "pay_1"  # case now references the failed payment
    assert case.recovery_probability is not None  # initial §28 estimate stored at detection

    # Verify audit created
    audit = db_session.query(AuditEvent).filter(AuditEvent.id == res["audit_id"]).first()
    assert audit is not None
    assert audit.case_id == case.id
    assert audit.event_type == "CASE_CREATED"
    assert audit.payload_json["trigger_event"] == "PAYMENT_FAILED"


def test_handle_payment_failed_is_idempotent(db_session):
    """A repeat PAYMENT_FAILED for the same payment returns the existing case (§38), no duplicate."""
    db_session.add(Customer(id="cust_1", name="Test", email="test@test.com",
                            risk_score=0.2, ltv_amount=6000))
    db_session.add(Payment(id="pay_1", customer_id="cust_1", amount=1500,
                           gateway="STRIPE", status="FAILED"))
    db_session.commit()

    event = EventPayload(
        event_type=EventType.PAYMENT_FAILED,
        customer_id="cust_1",
        payment_id="pay_1",
        amount=1500,
    )

    first = handle_event(db_session, event)
    second = handle_event(db_session, event)

    assert first["status"] == "success"
    assert second["status"] == "exists"
    assert second["case_id"] == first["case_id"]

    # Exactly one case and one audit row -- the repeat produced neither a duplicate case nor audit.
    assert db_session.query(RevenueRiskCase).count() == 1
    assert db_session.query(AuditEvent).count() == 1
