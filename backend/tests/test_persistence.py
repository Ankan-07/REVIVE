import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.schemas.customer import CustomerCreate
from app.schemas.case import RevenueRiskCaseCreate
from app.schemas.enums import CaseType, CaseStatus, Priority
from app.services.customer_service import create_customer, get_customer
from app.services.case_service import create_case, get_case


@pytest.fixture
def db_session():
    # Setup temporary SQLite in-memory database
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_customer_and_case_persistence(db_session):
    # 1. Create Customer
    customer_in = CustomerCreate(
        name="Acme Corp",
        email="billing@acme.com",
        phone="+1234567890",
        segment="Enterprise",
        ltv_amount=50000.0,
        risk_score=0.15,
    )
    customer = create_customer(db_session, customer_in)

    assert customer.id == "CUS-00001"
    assert customer.name == "Acme Corp"
    assert customer.email == "billing@acme.com"

    # Verify retrieval via get_customer service
    fetched_customer = get_customer(db_session, customer.id)
    assert fetched_customer is not None
    assert fetched_customer.id == "CUS-00001"
    assert fetched_customer.segment == "Enterprise"

    # 2. Create RevenueRiskCase linked to Customer
    case_in = RevenueRiskCaseCreate(
        customer_id=customer.id,
        case_type=CaseType.FAILED_PAYMENT,
        amount_at_risk=15000.0,
        priority=Priority.HIGH,
        risk_score=0.75,
    )
    case = create_case(db_session, case_in)

    assert case.id == "RR-00001"
    assert case.customer_id == "CUS-00001"
    assert case.case_type == CaseType.FAILED_PAYMENT
    assert case.status == CaseStatus.DETECTED
    assert case.amount_at_risk == 15000.0
    assert case.priority == Priority.HIGH

    # Verify retrieval via get_case service
    fetched_case = get_case(db_session, case.id)
    assert fetched_case is not None
    assert fetched_case.id == "RR-00001"
    assert fetched_case.customer_id == "CUS-00001"
    assert fetched_case.status == CaseStatus.DETECTED
