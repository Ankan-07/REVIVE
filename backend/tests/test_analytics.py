import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.db import Base, get_db
import app.models  # noqa: F401  (register every table on Base before create_all)
from app.main import app
from app.schemas.customer import CustomerCreate
from app.schemas.case import RevenueRiskCaseCreate
from app.schemas.enums import CaseType, Priority, OutcomeType, InterventionType
from app.services.customer_service import create_customer
from app.services.case_service import create_case, get_case_row
from app.services.intervention_service import create_executed
from app.services.outcome_service import record_outcome
from app.services.analytics_service import get_recovery_totals, get_intervention_stats


@pytest.fixture
def factory():
    # Single shared in-memory DB (StaticPool) so the seeding session and the HTTP request session
    # both see the same rows — a plain "sqlite:///:memory:" would give each connection its own DB.
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


def test_analytics_totals_and_filtering(db_session):
    # Setup test data
    customer_in = CustomerCreate(
        name="Test Corp",
        email="test@test.com",
        phone="123",
        segment="SMB",
        ltv_amount=5000.0,
        risk_score=0.1,
    )
    customer = create_customer(db_session, customer_in)

    # Case 1: Failed Payment, Recovered
    case1_in = RevenueRiskCaseCreate(
        customer_id=customer.id,
        case_type=CaseType.FAILED_PAYMENT,
        amount_at_risk=1000.0,
        priority=Priority.MEDIUM,
    )
    case1 = create_case(db_session, case1_in)
    # Manually backdate for filtering test
    case1_row = get_case_row(db_session, case1.id)
    case1_row.created_at = datetime.now(timezone.utc) - timedelta(days=10)
    db_session.commit()


    create_executed(
        db_session,
        case_id=case1.id,
        action=InterventionType.RETRY_PAYMENT.value,
        cost=10.0,
        idempotency_key="key1",
        result={"success": True}  # what a real tool execution stores
    )
    record_outcome(
        db_session,
        case_id=case1.id,
        outcome_type=OutcomeType.RECOVERED_FULL.value,
        gross_recovered=1000.0,
        cost_total=10.0,
        discount_total=0.0
    )

    # Case 2: Checkout Abandonment, Escalated (Cost but no recovery)
    case2_in = RevenueRiskCaseCreate(
        customer_id=customer.id,
        case_type=CaseType.ABANDONED_CHECKOUT,
        amount_at_risk=500.0,
        priority=Priority.MEDIUM,
    )
    case2 = create_case(db_session, case2_in)
    # created_at is today
    create_executed(
        db_session,
        case_id=case2.id,
        action=InterventionType.SEND_DISCOUNT_MESSAGE.value,
        cost=2.0,
        discount_amount=50.0,
        idempotency_key="key2",
        result={}
    )
    record_outcome(
        db_session,
        case_id=case2.id,
        outcome_type=OutcomeType.ESCALATED.value,
        gross_recovered=0.0,
        cost_total=2.0,
        discount_total=50.0
    )

    # 1. Test Global Aggregation
    totals = get_recovery_totals(db_session)
    assert totals.total_cases == 2
    assert totals.total_amount_at_risk == 1500.0
    assert totals.total_gross_recovered == 1000.0
    assert totals.total_intervention_costs == 12.0
    assert totals.total_discounts == 50.0
    # Net should be 1000 - 12 - 50 = 938.0
    assert totals.total_net_recovered == 938.0
    assert totals.recovery_rate == 0.5
    assert totals.average_recovery_time_hours is not None

    interventions = get_intervention_stats(db_session).stats
    assert len(interventions) == 2
    retry_stat = next(s for s in interventions if s.intervention_type == InterventionType.RETRY_PAYMENT.value)
    assert retry_stat.count == 1
    assert retry_stat.success_count == 1
    assert retry_stat.total_cost == 10.0

    discount_stat = next(s for s in interventions if s.intervention_type == InterventionType.SEND_DISCOUNT_MESSAGE.value)
    assert discount_stat.count == 1
    assert discount_stat.success_count == 0  # the escalated case's discount never "succeeded"

    # 2. Test specific filtering by case_type
    totals_failed = get_recovery_totals(db_session, case_type=CaseType.FAILED_PAYMENT.value)
    assert totals_failed.total_cases == 1
    assert totals_failed.total_amount_at_risk == 1000.0
    assert totals_failed.total_gross_recovered == 1000.0
    assert totals_failed.total_intervention_costs == 10.0
    assert totals_failed.total_discounts == 0.0
    assert totals_failed.total_net_recovered == 990.0
    assert totals_failed.recovery_rate == 1.0

    # 3. Test specific filtering by date
    # Filter for cases created in the last 5 days (should only catch case 2)
    start_date = datetime.now(timezone.utc) - timedelta(days=5)
    totals_recent = get_recovery_totals(db_session, start_date=start_date)
    assert totals_recent.total_cases == 1
    assert totals_recent.total_amount_at_risk == 500.0
    assert totals_recent.total_gross_recovered == 0.0
    assert totals_recent.total_intervention_costs == 2.0
    assert totals_recent.total_discounts == 50.0
    assert totals_recent.total_net_recovered == -52.0
    assert totals_recent.recovery_rate == 0.0
    assert totals_recent.average_recovery_time_hours is None  # nothing recovered in the window


def test_recovery_counts_distinct_cases_not_outcome_rows(db_session):
    """A case with more than one outcome row must still count as one case, and its stored gross/net
    must not be double-summed via the outcome-row count."""
    customer = create_customer(db_session, CustomerCreate(
        name="Dup Corp", email="dup@test.com", phone="1", segment="SMB",
        ltv_amount=1000.0, risk_score=0.1,
    ))
    case = create_case(db_session, RevenueRiskCaseCreate(
        customer_id=customer.id,
        case_type=CaseType.FAILED_PAYMENT,
        amount_at_risk=1000.0,
        priority=Priority.MEDIUM,
    ))
    # Two outcome rows for the SAME case (e.g. an escalate→resume path that writes twice).
    record_outcome(
        db_session, case_id=case.id, outcome_type=OutcomeType.ESCALATED.value,
        gross_recovered=0.0, cost_total=5.0, discount_total=0.0,
    )
    record_outcome(
        db_session, case_id=case.id, outcome_type=OutcomeType.RECOVERED_FULL.value,
        gross_recovered=1000.0, cost_total=5.0, discount_total=0.0,
    )

    totals = get_recovery_totals(db_session)
    # Distinct case count, not the 2 outcome rows.
    assert totals.total_cases == 1


def test_recovery_and_intervention_endpoints_over_http(db_session, client):
    """Exercise the HTTP layer end-to-end: router registration, the /analytics prefix,
    query-param coercion, and response_model serialization."""
    customer = create_customer(db_session, CustomerCreate(
        name="HTTP Corp", email="http@test.com", phone="1", segment="SMB",
        ltv_amount=1000.0, risk_score=0.1,
    ))
    case = create_case(db_session, RevenueRiskCaseCreate(
        customer_id=customer.id,
        case_type=CaseType.FAILED_PAYMENT,
        amount_at_risk=1000.0,
        priority=Priority.MEDIUM,
    ))
    create_executed(
        db_session,
        case_id=case.id,
        action=InterventionType.SEND_DISCOUNT_MESSAGE.value,
        cost=5.0,
        discount_amount=20.0,
        idempotency_key="http-key",
        result={},
    )
    record_outcome(
        db_session,
        case_id=case.id,
        outcome_type=OutcomeType.RECOVERED_FULL.value,
        gross_recovered=1000.0,
        cost_total=5.0,
        discount_total=20.0,
    )

    # /analytics/recovery
    resp = client.get("/analytics/recovery")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_cases"] == 1
    assert body["total_gross_recovered"] == 1000.0
    assert body["total_intervention_costs"] == 5.0
    assert body["total_discounts"] == 20.0
    assert body["total_net_recovered"] == 975.0  # 1000 - 5 - 20

    # Query-param coercion: a future start_date filters everything out.
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    resp_future = client.get("/analytics/recovery", params={"start_date": future})
    assert resp_future.status_code == 200, resp_future.text
    assert resp_future.json()["total_cases"] == 0

    # /analytics/interventions
    resp_int = client.get("/analytics/interventions")
    assert resp_int.status_code == 200, resp_int.text
    stats = resp_int.json()["stats"]
    assert len(stats) == 1
    assert stats[0]["intervention_type"] == InterventionType.SEND_DISCOUNT_MESSAGE.value
    assert stats[0]["count"] == 1
    assert stats[0]["total_cost"] == 5.0


def test_analytics_endpoints_in_prod_default_to_live(db_session, client, monkeypatch):
    """In production (APP_ENV=prod), HTTP analytics endpoints should default to origin='live'
    instead of throwing unhandled 500 ValueError when origin parameter is omitted by client."""
    from app.config import settings
    monkeypatch.setattr(settings, "app_env", "prod")

    resp_recovery = client.get("/analytics/recovery")
    assert resp_recovery.status_code == 200, resp_recovery.text
    assert resp_recovery.json()["total_cases"] == 0

    resp_interventions = client.get("/analytics/interventions")
    assert resp_interventions.status_code == 200, resp_interventions.text
    assert resp_interventions.json()["stats"] == []
