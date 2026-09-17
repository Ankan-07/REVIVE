"""Comprehensive TDD Test Suite for Phase E1 & E1.2: Reconciliation & Escalation SLA.

Covers:
- E1.1: Reconcile clean match (ledger matches gateway truth -> 0 mismatches)
- E1.2: Reconcile amount discrepancy (gateway captured amount != gross_recovered -> mismatch, escalation row, audit)
- E1.3: Reconcile unreflected refund/dispute (gateway reports refund not on ledger -> mismatch, escalation)
- E1.4: Escalation SLA computation (sla_due_at populated on creation)
- E1.5: Aging escalation SLA alert scanner (finds unassigned escalations past sla_due_at)
- E1.6: Reconciliation Dashboard Endpoint (GET /analytics/reconciliation returns report)
"""
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_db, utc_now
from app.domain.ids import generate_id
from app.main import app as fastapi_app
from app.models.case import RevenueRiskCase
from app.models.customer import Customer
from app.models.escalation import Escalation
from app.schemas.enums import CaseStatus, CaseType, EscalationReason, OutcomeType
from app.services import (
    escalation_service,
    outcome_service,
    provider_object_service,
    reconciliation_service,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import Base

    db_path = tmp_path / "test_phase_e.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": 30.0, "check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr("app.db.SessionLocal", session_factory)
    monkeypatch.setattr("app.jobs.worker.SessionLocal", session_factory, raising=False)

    def _get_db_override():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    fastapi_app.dependency_overrides[get_db] = _get_db_override
    session = session_factory()
    try:
        yield session
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


@pytest.fixture
def client(db):
    return TestClient(fastapi_app)


@pytest.fixture(autouse=True)
def setup_phase_e_env():
    orig_env = settings.app_env
    orig_key_id = settings.razorpay_key_id
    orig_key_secret = settings.razorpay_key_secret
    orig_alert_email = settings.admin_alert_email

    settings.app_env = "dev"
    settings.razorpay_key_id = "rzp_test_phase_e_key"
    settings.razorpay_key_secret = "phase_e_secret"
    settings.admin_alert_email = "alerts@revive.test"

    yield

    settings.app_env = orig_env
    settings.razorpay_key_id = orig_key_id
    settings.razorpay_key_secret = orig_key_secret
    settings.admin_alert_email = orig_alert_email


def _create_test_case_with_outcome(db, *, gross: float = 500.0, payment_id: str = "pay_rec_001"):
    cust = Customer(
        id=generate_id("CUS", db),
        name="Reconcile Customer",
        email="rec_cust@example.com",
        phone="+919999988888",
        origin="live",
    )
    db.add(cust)
    db.flush()

    case = RevenueRiskCase(
        id=generate_id("RR", db),
        customer_id=cust.id,
        payment_id=payment_id,
        case_type=CaseType.FAILED_PAYMENT.value,
        origin="live",
        status=CaseStatus.RECOVERED.value,
        amount_at_risk=gross,
    )
    db.add(case)
    db.flush()

    outcome_service.record_outcome(
        db,
        case_id=case.id,
        outcome_type=OutcomeType.RECOVERED_FULL.value,
        gross_recovered=gross,
        cost_total=5.0,
        discount_total=0.0,
        gateway_fee_paise=1180,
        verified=True,
    )

    pobj = provider_object_service.record_object(
        db,
        case_id=case.id,
        object_type="payment",
        provider_object_id=payment_id,
        amount_paise=int(gross * 100),
        status="captured",
        fee_paise=1180,
    )
    db.commit()
    return case, pobj


# ======================================================================================
# E1.1 & E1.2: Reconciliation Matching & Discrepancy Detection
# ======================================================================================

def test_e1_reconcile_clean_matching(db, monkeypatch):
    """E1: Reconcile finds zero mismatches when provider objects match gateway records exactly."""
    case, pobj = _create_test_case_with_outcome(db, gross=500.0, payment_id="pay_match_001")

    def _mock_fetch_payment(payment_id: str):
        return {
            "id": payment_id,
            "amount": 50000,  # ₹500.00
            "amount_refunded": 0,
            "status": "captured",
            "currency": "INR",
        }

    monkeypatch.setattr("app.services.razorpay_service._fetch_payment_on_gateway", _mock_fetch_payment, raising=False)

    report = reconciliation_service.reconcile_all(db)
    assert report["total_checked"] >= 1
    assert report["mismatches"] == 0
    assert report["matched"] >= 1
    assert len(report["mismatch_details"]) == 0


def test_e1_reconcile_amount_mismatch_creates_escalation(db, monkeypatch):
    """E1: Reconcile flags mismatch when gateway captured amount differs from internal gross recovery.
    
    Creates an Escalation row with reason 'RECONCILIATION_MISMATCH' and records an audit row.
    """
    case, pobj = _create_test_case_with_outcome(db, gross=500.0, payment_id="pay_discrepancy_001")

    # Gateway reports only 35000 paise (₹350.00) instead of expected ₹500.00
    def _mock_fetch_payment(payment_id: str):
        return {
            "id": payment_id,
            "amount": 35000,  # ₹350.00
            "amount_refunded": 0,
            "status": "captured",
            "currency": "INR",
        }

    monkeypatch.setattr("app.services.razorpay_service._fetch_payment_on_gateway", _mock_fetch_payment, raising=False)

    report = reconciliation_service.reconcile_all(db)
    assert report["mismatches"] >= 1

    # Escalation row must be created for this case
    esc = db.query(Escalation).filter(Escalation.case_id == case.id).first()
    assert esc is not None
    assert esc.reason == "RECONCILIATION_MISMATCH"
    assert esc.priority == "HIGH"
    assert "Discrepancy" in esc.notes or "mismatch" in esc.notes.lower()


def test_e1_reconcile_unreflected_refund_detected(db, monkeypatch):
    """E1: Reconcile flags mismatch when gateway shows payment was refunded but internal outcome is not REFUNDED."""
    case, pobj = _create_test_case_with_outcome(db, gross=500.0, payment_id="pay_refund_unreflected")

    # Gateway reports full refund of 50000 paise
    def _mock_fetch_payment(payment_id: str):
        return {
            "id": payment_id,
            "amount": 50000,
            "amount_refunded": 50000,
            "status": "refunded",
            "currency": "INR",
        }

    monkeypatch.setattr("app.services.razorpay_service._fetch_payment_on_gateway", _mock_fetch_payment, raising=False)

    report = reconciliation_service.reconcile_all(db)
    assert report["mismatches"] >= 1

    esc = db.query(Escalation).filter(Escalation.case_id == case.id).first()
    assert esc is not None
    assert esc.reason == "RECONCILIATION_MISMATCH"
    assert "refund" in esc.notes.lower()


# ======================================================================================
# E1.2: Escalation SLA & Aging Alerts
# ======================================================================================

def test_e1_escalation_sla_due_at_populated_on_creation(db):
    """E1.2: When an escalation is created, sla_due_at is set to created_at + SLA_ESCALATION_HOURS."""
    case, _ = _create_test_case_with_outcome(db, gross=100.0, payment_id="pay_sla_001")

    esc = escalation_service.create_escalation(
        db,
        case_id=case.id,
        reason=EscalationReason.AGENT_LOW_CONFIDENCE.value,
        priority="HIGH",
        notes="Testing SLA calculation",
    )
    assert esc.sla_due_at is not None
    # Default SLA is 4 hours
    diff_hours = (esc.sla_due_at - esc.created_at).total_seconds() / 3600.0
    assert abs(diff_hours - 4.0) < 0.1


def test_e1_aging_escalation_sla_alert_scanner(db):
    """E1.2: check_escalation_slas detects open unassigned escalations that passed sla_due_at."""
    case, _ = _create_test_case_with_outcome(db, gross=100.0, payment_id="pay_sla_aging_001")

    # Create an old unassigned escalation with sla_due_at in the past
    past_due = utc_now() - timedelta(hours=2)
    esc = Escalation(
        id=generate_id("ESC", db),
        case_id=case.id,
        reason=EscalationReason.DISPUTE_FILED.value,
        priority="HIGH",
        status="OPEN",
        owner_id=None,
        created_at=past_due - timedelta(hours=4),
        sla_due_at=past_due,
        notes="Overdue dispute",
    )
    db.add(esc)
    db.commit()

    breached = reconciliation_service.check_escalation_slas(db)
    assert len(breached) >= 1
    breached_ids = [b["escalation_id"] for b in breached]
    assert esc.id in breached_ids


# ======================================================================================
# E1 Dashboard Endpoint
# ======================================================================================

def test_e1_reconciliation_api_endpoint(client: TestClient, db, monkeypatch):
    """E1: GET /analytics/reconciliation returns latest reconciliation summary and SLA aging alerts."""
    from app.auth import AuthContext, get_current_auth

    fastapi_app.dependency_overrides[get_current_auth] = lambda: AuthContext(
        key_id="k_test_operator",
        name="operator_user",
        scopes={"operator", "internal"},
    )
    try:
        resp = client.get("/analytics/reconciliation")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "total_checked" in data
        assert "mismatches" in data
        assert "aging_escalations" in data
    finally:
        fastapi_app.dependency_overrides.pop(get_current_auth, None)
