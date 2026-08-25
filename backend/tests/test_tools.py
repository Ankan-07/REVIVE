import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
import app.models  # noqa: F401 -- registers every table
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.metric import GatewayMetric
from app.models.audit import AuditEvent
from app.models.intervention import Intervention
from app.models.case import RevenueRiskCase
from app.schemas.enums import PaymentStatus
from app.tools.payment_tools import retry_payment
from app.tools.base import FailureCategory

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()

def _seed_scenario(db, error_code="timeout"):
    from datetime import datetime
    t = datetime(2026, 1, 1)

    db.add(GatewayMetric(id="GWM-00001", gateway_name="PAYU", success_rate=0.50,
                         baseline_success_rate=0.97, latency_ms=1200.0,
                         health_status="DEGRADED", recorded_at=t))
    db.add(Customer(id="CUS-00001", name="Alice", email="a@example.com",
                    segment="VIP", ltv_amount=5000.0, risk_score=0.1, intent_score=1.0))
    # We set recovery_roll to 0.99 so the payment always fails in simulation (0.99 > 0.5)
    db.add(Payment(id="PAY-00001", customer_id="CUS-00001", amount=999.0, currency="INR",
                   gateway="PAYU", status=PaymentStatus.FAILED.value, error_code=error_code,
                   error_message="Payment failed", attempt_count=1,
                   method_health=1.0, recovery_roll=0.99))
    db.add(RevenueRiskCase(id="RR-00001", customer_id="CUS-00001", payment_id="PAY-00001", status="DETECTED", case_type="FAILED_PAYMENT", amount_at_risk=999.0))
    db.commit()

def test_auth_failure_wrong_caller(db_session):
    _seed_scenario(db_session)
    res = retry_payment(db_session, case_id="RR-00001", payment_id="PAY-00001", attempt=1, caller="untrusted")
    assert res.success is False
    assert res.error_code == "AUTH_FAILURE"

def test_param_validation_bad_case_id(db_session):
    _seed_scenario(db_session)
    res = retry_payment(db_session, case_id="bad", payment_id="PAY-00001", attempt=1)
    assert res.success is False
    assert res.error_code == "PARAM_VALIDATION_FAILURE"

def test_retryable_error_category(db_session):
    _seed_scenario(db_session, error_code="timeout")
    res = retry_payment(db_session, case_id="RR-00001", payment_id="PAY-00001", attempt=1)
    assert res.success is False
    assert res.failure_category == FailureCategory.RETRYABLE_SYSTEM_FAILURE

def test_non_retryable_error_category(db_session):
    _seed_scenario(db_session, error_code="expired_card")
    res = retry_payment(db_session, case_id="RR-00001", payment_id="PAY-00001", attempt=1)
    assert res.success is False
    assert res.failure_category == FailureCategory.NON_RETRYABLE_USER_FAILURE
    assert res.retryable is False

def test_idempotency_replay(db_session):
    _seed_scenario(db_session, error_code="timeout")
    res1 = retry_payment(db_session, case_id="RR-00001", payment_id="PAY-00001", attempt=1)
    res2 = retry_payment(db_session, case_id="RR-00001", payment_id="PAY-00001", attempt=1)
    
    assert res1.success == res2.success
    assert res1.detail != res2.detail
    assert "idempotent" in res2.detail.lower()
    
    interventions = db_session.query(Intervention).filter(Intervention.case_id == "RR-00001").all()
    assert len(interventions) == 1

def test_pre_execution_audit_event_written(db_session):
    _seed_scenario(db_session, error_code="timeout")
    retry_payment(db_session, case_id="RR-00001", payment_id="PAY-00001", attempt=1)
    
    audit_events = db_session.query(AuditEvent).filter(
        AuditEvent.case_id == "RR-00001",
        AuditEvent.event_type == "TOOL_VALIDATION_PASSED"
    ).all()
    assert len(audit_events) == 1
