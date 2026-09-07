import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db import Base
import app.models  # noqa: F401
from app.models.case import RevenueRiskCase
from app.models.customer import Customer
from app.models.provider_object import ProviderObject
from app.services import provider_object_service
from app.agent.runner import _default_checkpointer


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_provider_object_unique_constraint(db_session):
    """A1.7: Database rejects duplicate provider_object_id with IntegrityError."""
    p1 = ProviderObject(
        id="POBJ-001",
        case_id="RR-001",
        object_type="order",
        provider_object_id="order_duplicate_test",
        amount_paise=100000,
        status="created",
    )
    db_session.add(p1)
    db_session.commit()

    p2 = ProviderObject(
        id="POBJ-002",
        case_id="RR-001",
        object_type="order",
        provider_object_id="order_duplicate_test",
        amount_paise=100000,
        status="created",
    )
    db_session.add(p2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_provider_object_service_lifecycle(db_session):
    """A1.7: provider_object_service records, updates, and lists objects for a case."""
    cust = Customer(id="CUS-010", name="Dan", email="d@example.com")
    case = RevenueRiskCase(id="RR-010", customer_id="CUS-010", status="OPEN", case_type="FAILED_PAYMENT", amount_at_risk=2000.0)
    db_session.add_all([cust, case])
    db_session.commit()

    # 1. Record an order
    obj1 = provider_object_service.record_object(
        db_session,
        case_id="RR-010",
        object_type="order",
        provider_object_id="order_test_123",
        amount_paise=200000,
        status="created",
    )
    assert obj1.provider_object_id == "order_test_123"
    assert obj1.status == "created"

    # 2. Record a payment link for the same case
    obj2 = provider_object_service.record_object(
        db_session,
        case_id="RR-010",
        object_type="link",
        provider_object_id="plink_test_456",
        amount_paise=200000,
        status="active",
    )
    assert obj2.object_type == "link"

    # 3. Update status of the order to paid
    updated = provider_object_service.update_status(
        db_session,
        provider_object_id="order_test_123",
        status="paid",
        fee_paise=4000,
    )
    assert updated is not None
    assert updated.status == "paid"
    assert updated.fee_paise == 4000

    # 4. Lookup by provider id
    lookup = provider_object_service.get_by_provider_id(db_session, "plink_test_456")
    assert lookup is not None
    assert lookup.id == obj2.id

    # 5. List all objects for the case
    case_objects = provider_object_service.list_for_case(db_session, "RR-010")
    assert len(case_objects) == 2
    types = [o.object_type for o in case_objects]
    assert "order" in types
    assert "link" in types


def test_default_checkpointer_runs_cleanly():
    """A1.6: _default_checkpointer initializes without error."""
    saver = _default_checkpointer()
    assert saver is not None


def test_razorpay_order_and_settle_records_provider_objects(db_session, monkeypatch):
    """A1.7: create_order_for_payment and verify_and_settle record in provider_objects."""
    import hashlib
    import hmac
    from app.models.payment import Payment
    from app.schemas.enums import PaymentStatus
    from app.services import razorpay_service

    key_id = "rzp_test_testkey123"
    key_secret = "testsecret123"
    monkeypatch.setenv("RAZORPAY_KEY_ID", key_id)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", key_secret)

    # Monkeypatch gateway call
    monkeypatch.setattr(
        razorpay_service,
        "_create_order_on_gateway",
        lambda **kw: {"id": "order_mock_999", "amount": kw["amount_paise"], "currency": "INR"},
    )

    cust = Customer(id="CUS-099", name="Eve", email="eve@example.com")
    pay = Payment(
        id="PAY-099",
        customer_id="CUS-099",
        amount=1500.0,
        currency="INR",
        gateway="RAZORPAY",
        status=PaymentStatus.FAILED.value,
        recovery_roll=0.5,
    )
    case = RevenueRiskCase(
        id="RR-099",
        customer_id="CUS-099",
        payment_id="PAY-099",
        status="OPEN",
        case_type="FAILED_PAYMENT",
        amount_at_risk=1500.0,
    )
    db_session.add_all([cust, pay, case])
    db_session.commit()

    # 1. Create order
    res = razorpay_service.create_order_for_payment(db_session, payment_id="PAY-099")
    assert res["order_id"] == "order_mock_999"

    # Verify order recorded in provider_objects
    order_obj = provider_object_service.get_by_provider_id(db_session, "order_mock_999")
    assert order_obj is not None
    assert order_obj.case_id == "RR-099"
    assert order_obj.object_type == "order"
    assert order_obj.amount_paise == 150000
    assert order_obj.status == "created"

    # 2. Settle payment
    sig = hmac.new(
        key_secret.encode("utf-8"),
        b"order_mock_999|pay_mock_888",
        hashlib.sha256,
    ).hexdigest()

    settle_res = razorpay_service.verify_and_settle(
        db_session,
        payment_id="PAY-099",
        order_id="order_mock_999",
        razorpay_payment_id="pay_mock_888",
        razorpay_signature=sig,
    )
    assert settle_res["status"] == "success"

    # Verify payment recorded and order marked paid
    pay_obj = provider_object_service.get_by_provider_id(db_session, "pay_mock_888")
    assert pay_obj is not None
    assert pay_obj.case_id == "RR-099"
    assert pay_obj.object_type == "payment"
    assert pay_obj.status == "captured"
    assert pay_obj.amount_paise == 150000

    order_updated = provider_object_service.get_by_provider_id(db_session, "order_mock_999")
    assert order_updated is not None
    assert order_updated.status == "paid"

