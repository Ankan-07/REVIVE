from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.db import Base, get_db, utc_now
import app.models  # noqa: F401
from app.main import app
from app.models.case import RevenueRiskCase
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.outcome import RecoveryOutcome
from app.models.intervention import Intervention
from app.schemas.customer import CustomerCreate
from app.schemas.case import RevenueRiskCaseCreate
from app.schemas.enums import CaseType, CaseStatus, Priority, OutcomeType, InterventionType
from app.services.customer_service import create_customer
from app.services.case_service import create_case, list_cases
from app.services.analytics_service import get_recovery_totals, get_intervention_stats
from app.services.intervention_service import create_executed
from app.services.outcome_service import record_outcome
from app.services.event_service import handle_event
from app.schemas.events import EventPayload, EventType


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
def db_session(factory):
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(factory):
    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_origin_defaults_and_explicit_assignment(db_session):
    """A1.8: Customer, Payment, and Case must default origin to 'lab' or accept 'live'."""
    cust_lab = create_customer(db_session, CustomerCreate(name="Lab User", email="lab@test.com"))
    cust_live = create_customer(db_session, CustomerCreate(name="Live User", email="live@test.com", origin="live"))
    assert cust_lab.origin == "lab"
    assert cust_live.origin == "live"

    case_lab = create_case(db_session, RevenueRiskCaseCreate(
        customer_id=cust_lab.id,
        case_type=CaseType.FAILED_PAYMENT,
        amount_at_risk=100.0,
    ))
    case_live = create_case(db_session, RevenueRiskCaseCreate(
        customer_id=cust_live.id,
        case_type=CaseType.FAILED_PAYMENT,
        amount_at_risk=200.0,
        origin="live",
    ))
    assert case_lab.origin == "lab"
    assert case_live.origin == "live"

    # Payment model default and explicit origin
    pay_lab = Payment(
        id="PAY-LAB-1",
        customer_id=cust_lab.id,
        amount=100.0,
        gateway="razorpay",
        status="FAILED",
    )
    pay_live = Payment(
        id="PAY-LIVE-1",
        customer_id=cust_live.id,
        amount=200.0,
        gateway="razorpay",
        origin="live",
        status="FAILED",
    )
    db_session.add_all([pay_lab, pay_live])
    db_session.commit()

    assert pay_lab.origin == "lab"
    assert pay_live.origin == "live"


def test_event_service_propagates_origin_from_payment(db_session):
    """A1.8: Event trigger must inherit payment's origin (e.g. 'live')."""
    cust = Customer(id="CUS-LIVE-EV", name="Live Corp", email="corp@live.com", origin="live")
    pay = Payment(
        id="PAY-LIVE-EV",
        customer_id=cust.id,
        amount=5000.0,
        gateway="razorpay",
        origin="live",
        status="FAILED",
    )
    db_session.add_all([cust, pay])
    db_session.commit()

    result = handle_event(
        db_session,
        EventPayload(
            event_type=EventType.PAYMENT_FAILED,
            customer_id=cust.id,
            payment_id=pay.id,
            amount=5000.0,
        ),
    )
    case_id = result["case_id"]
    case = db_session.query(RevenueRiskCase).filter(RevenueRiskCase.id == case_id).first()
    assert case is not None
    assert case.origin == "live"


def test_list_cases_origin_filter(db_session):
    """A1.8: list_cases service and endpoint filter by origin."""
    cust = create_customer(db_session, CustomerCreate(name="Cust", email="c@test.com"))
    case1 = create_case(db_session, RevenueRiskCaseCreate(customer_id=cust.id, case_type=CaseType.FAILED_PAYMENT, amount_at_risk=100.0, origin="lab"))
    case2 = create_case(db_session, RevenueRiskCaseCreate(customer_id=cust.id, case_type=CaseType.FAILED_PAYMENT, amount_at_risk=200.0, origin="live"))

    all_cases = list_cases(db_session)
    lab_cases = list_cases(db_session, origin="lab")
    live_cases = list_cases(db_session, origin="live")

    assert len(all_cases) >= 2
    assert any(c.id == case1.id for c in lab_cases)
    assert not any(c.id == case2.id for c in lab_cases)
    assert any(c.id == case2.id for c in live_cases)
    assert not any(c.id == case1.id for c in live_cases)


def test_analytics_isolation_by_origin(db_session, client):
    """A1.8: Analytics recovery totals and intervention stats filter accurately by origin."""
    cust_lab = create_customer(db_session, CustomerCreate(name="Lab User", email="lab@u.com"))
    cust_live = create_customer(db_session, CustomerCreate(name="Live User", email="live@u.com", origin="live"))

    case_lab = create_case(db_session, RevenueRiskCaseCreate(customer_id=cust_lab.id, case_type=CaseType.FAILED_PAYMENT, amount_at_risk=1000.0, origin="lab"))
    case_live = create_case(db_session, RevenueRiskCaseCreate(customer_id=cust_live.id, case_type=CaseType.FAILED_PAYMENT, amount_at_risk=5000.0, origin="live"))

    # Outcomes
    record_outcome(db_session, case_id=case_lab.id, outcome_type=OutcomeType.RECOVERED_FULL.value, gross_recovered=1000.0, cost_total=10.0, discount_total=0.0)
    record_outcome(db_session, case_id=case_live.id, outcome_type=OutcomeType.RECOVERED_FULL.value, gross_recovered=5000.0, cost_total=50.0, discount_total=100.0)

    # Interventions
    create_executed(db_session, case_id=case_lab.id, action=InterventionType.RETRY_PAYMENT.value, cost=10.0, result={"success": True}, idempotency_key="idemp-lab-1")
    create_executed(db_session, case_id=case_live.id, action=InterventionType.CREATE_PAYMENT_LINK.value, cost=50.0, discount_amount=100.0, result={"success": True}, idempotency_key="idemp-live-1")

    # Test Service Isolation
    totals_lab = get_recovery_totals(db_session, origin="lab")
    assert totals_lab.total_cases == 1
    assert totals_lab.total_amount_at_risk == 1000.0
    assert totals_lab.total_gross_recovered == 1000.0
    assert totals_lab.total_net_recovered == 990.0

    totals_live = get_recovery_totals(db_session, origin="live")
    assert totals_live.total_cases == 1
    assert totals_live.total_amount_at_risk == 5000.0
    assert totals_live.total_gross_recovered == 5000.0
    assert totals_live.total_net_recovered == 4850.0

    int_lab = get_intervention_stats(db_session, origin="lab")
    assert len(int_lab.stats) == 1
    assert int_lab.stats[0].intervention_type == InterventionType.RETRY_PAYMENT.value

    int_live = get_intervention_stats(db_session, origin="live")
    assert len(int_live.stats) == 1
    assert int_live.stats[0].intervention_type == InterventionType.CREATE_PAYMENT_LINK.value

    # Test HTTP Endpoints
    resp_lab = client.get("/analytics/recovery", params={"origin": "lab"})
    assert resp_lab.status_code == 200
    assert resp_lab.json()["total_amount_at_risk"] == 1000.0

    resp_live = client.get("/analytics/recovery", params={"origin": "live"})
    assert resp_live.status_code == 200
    assert resp_live.json()["total_amount_at_risk"] == 5000.0

    resp_cases_live = client.get("/cases", params={"origin": "live"})
    assert resp_cases_live.status_code == 200
    live_ids = [c["id"] for c in resp_cases_live.json()]
    assert case_live.id in live_ids
    assert case_lab.id not in live_ids


def test_utc_now_and_timezone_aware_calculations(db_session):
    """A1.8: Ensure utc_now returns timezone-aware UTC datetime and time deltas calculate safely."""
    now = utc_now()
    assert now.tzinfo is not None
    assert now.tzinfo == timezone.utc

    cust = create_customer(db_session, CustomerCreate(name="TZ User", email="tz@test.com"))
    case = create_case(db_session, RevenueRiskCaseCreate(customer_id=cust.id, case_type=CaseType.FAILED_PAYMENT, amount_at_risk=100.0))

    # Test that outcome with verified_at calculates recovery time without TypeError
    outcome = record_outcome(db_session, case_id=case.id, outcome_type=OutcomeType.RECOVERED_FULL.value, gross_recovered=100.0, cost_total=0.0)
    assert outcome.verified_at is not None

    totals = get_recovery_totals(db_session)
    assert totals.total_cases == 1
    assert totals.average_recovery_time_hours is not None
