"""Comprehensive TDD Test Suite for Phase D: Real Detection for All Three Leak Types.

Covers:
- D1: Failed Payments Verified Ingest
  * payment.failed webhook re-fetches authoritative amount from Razorpay Orders API seam
  * Tampered payload amounts are overridden by gateway truth
  * Ingested case has origin='live' and status='DETECTED'
- D2: Abandoned Checkouts
  * payment_link.expired webhook with uncased payment link creates ABANDONED_CHECKOUT case (origin='live')
  * scan_abandoned_checkouts finds links unpaid past threshold and creates ABANDONED_CHECKOUT cases
- D3: Overdue Invoices
  * invoice.expired webhook with uncased invoice creates OVERDUE_INVOICE case (origin='live')
  * scan_overdue_invoices polls Razorpay Invoices API and creates OVERDUE_INVOICE cases (origin='live')
- D4: Pipeline Segregation & Webhook Schema Validation
  * POST /events/detect is blocked in APP_ENV=prod with HTTP 403
  * Lab detector strictly tags cases with origin='sim'
  * Malformed webhook payloads are rejected with HTTP 400
"""
import hashlib
import hmac
import json
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_db
from app.main import app as fastapi_app
from app.models.case import RevenueRiskCase
from app.models.customer import Customer
from app.models.provider_event import ProviderEvent
from app.models.provider_object import ProviderObject
from app.schemas.enums import CaseStatus, CaseType
from app.services import provider_event_service, provider_object_service, razorpay_service
from app.services.detection_service import scan_abandoned_checkouts, scan_overdue_invoices

WEBHOOK_SECRET = "phase_d_test_secret_xyz"


@pytest.fixture
def db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import Base

    db_path = tmp_path / "test_phase_d.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": 30.0, "check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr("app.db.SessionLocal", session_factory)
    monkeypatch.setattr("app.api.webhooks.SessionLocal", session_factory, raising=False)
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
def setup_phase_d_env():
    orig_secret = settings.razorpay_webhook_secret
    orig_env = settings.app_env
    orig_sync = settings.sync_run_agent
    orig_key_id = settings.razorpay_key_id
    orig_key_secret = settings.razorpay_key_secret

    settings.razorpay_webhook_secret = WEBHOOK_SECRET
    settings.app_env = "dev"
    settings.sync_run_agent = True
    settings.razorpay_key_id = "rzp_test_phase_d_key"
    settings.razorpay_key_secret = "phase_d_secret"

    yield

    settings.razorpay_webhook_secret = orig_secret
    settings.app_env = orig_env
    settings.sync_run_agent = orig_sync
    settings.razorpay_key_id = orig_key_id
    settings.razorpay_key_secret = orig_key_secret


def _sign(payload_bytes: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


# ======================================================================================
# D1: Verified Ingest for Failed Payments
# ======================================================================================

def test_d1_verified_ingest_refetches_authoritative_amount(db, monkeypatch):
    """D1: When payment.failed arrives, verified ingest fetches order from Razorpay API seam.
    
    If payload claims amount=1000 paise (₹10), but Razorpay order actually has 75000 paise (₹750),
    the case is created with amount_at_risk=750.0 and origin='live'.
    """
    tampered_payload_amount = 1000  # ₹10
    authoritative_order_amount = 75000  # ₹750

    # Monkeypatch gateway seam for fetching order
    def _mock_fetch_order(order_id: str):
        return {
            "id": order_id,
            "amount": authoritative_order_amount,
            "currency": "INR",
            "status": "attempted",
        }

    monkeypatch.setattr("app.services.razorpay_service._fetch_order_on_gateway", _mock_fetch_order, raising=False)

    payload = {
        "id": "evt_d1_001",
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_d1_001",
                    "order_id": "order_d1_authoritative",
                    "amount": tampered_payload_amount,
                    "currency": "INR",
                    "status": "failed",
                    "email": "verified_customer@example.com",
                    "contact": "+919876543210",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Payment was declined by bank",
                }
            }
        },
    }

    event_id, is_new, _ = provider_event_service.record_raw_event(
        db,
        razorpay_event_id=payload["id"],
        event_type=payload["event"],
        payload_json=payload,
    )

    res = provider_event_service.process_provider_event(db, event_id)
    assert res["status"] == "processed"
    case_id = res["case_id"]
    assert case_id is not None

    case = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == case_id).first()
    assert case is not None
    assert case.case_type == CaseType.FAILED_PAYMENT.value
    assert case.origin == "live"
    # Crucial assertion: Amount was verified against order API seam, NOT trusting payload!
    assert case.amount_at_risk == 750.0


# ======================================================================================
# D2: Abandoned Checkouts (Webhook & Scanner)
# ======================================================================================

def test_d2_payment_link_expired_creates_abandoned_checkout_case(db):
    """D2: An uncased payment_link.expired webhook automatically creates an ABANDONED_CHECKOUT case (origin='live')."""
    payload = {
        "id": "evt_d2_expired_001",
        "event": "payment_link.expired",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": "plink_d2_orphan",
                    "amount": 299900,  # ₹2999.00
                    "currency": "INR",
                    "status": "expired",
                    "customer": {
                        "name": "Abandoned Shopper",
                        "email": "shopper@example.com",
                        "contact": "+919811122233",
                    },
                    "description": "Cart items checkout",
                }
            }
        },
    }

    event_id, _, _ = provider_event_service.record_raw_event(
        db,
        razorpay_event_id=payload["id"],
        event_type=payload["event"],
        payload_json=payload,
    )

    res = provider_event_service.process_provider_event(db, event_id)
    assert res["status"] == "processed"
    case_id = res["case_id"]
    assert case_id is not None

    case = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == case_id).first()
    assert case is not None
    assert case.case_type == CaseType.ABANDONED_CHECKOUT.value
    assert case.origin == "live"
    assert case.amount_at_risk == 2999.0
    assert case.status == CaseStatus.DETECTED.value


def test_d2_scan_abandoned_checkouts_creates_cases_for_unpaid_links(db, monkeypatch):
    """D2: scan_abandoned_checkouts detects unpaid payment links past abandon_after_hours threshold."""
    # Pre-populate an active unpaid payment link in provider_objects without a case
    pobj = provider_object_service.record_object(
        db,
        case_id=None,
        object_type="payment_link",
        provider_object_id="plink_unpaid_old",
        amount_paise=150000,  # ₹1500.00
        status="created",
    )

    # Mock gateway returning payment link status as expired or unpaid past hours
    def _mock_fetch_payment_link(link_id: str):
        return {
            "id": link_id,
            "amount": 150000,
            "currency": "INR",
            "status": "expired",
            "customer": {"name": "Old Link User", "email": "oldlink@example.com", "contact": "+919000000001"},
        }

    monkeypatch.setattr("app.services.razorpay_service._fetch_payment_link_on_gateway", _mock_fetch_payment_link, raising=False)

    created_cases = scan_abandoned_checkouts(db, abandon_after_hours=2)
    assert len(created_cases) >= 1
    case = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == created_cases[0]).first()
    assert case is not None
    assert case.case_type == CaseType.ABANDONED_CHECKOUT.value
    assert case.origin == "live"
    assert case.amount_at_risk == 1500.0

    # Running it again is idempotent
    second_run = scan_abandoned_checkouts(db, abandon_after_hours=2)
    assert len(second_run) == 0


# ======================================================================================
# D3: Overdue Invoices (Webhook & Scanner)
# ======================================================================================

def test_d3_invoice_expired_creates_overdue_invoice_case(db):
    """D3: An uncased invoice.expired webhook automatically creates an OVERDUE_INVOICE case (origin='live')."""
    payload = {
        "id": "evt_d3_inv_001",
        "event": "invoice.expired",
        "payload": {
            "invoice": {
                "entity": {
                    "id": "inv_d3_orphan",
                    "amount": 1200000,  # ₹12000.00
                    "currency": "INR",
                    "status": "expired",
                    "customer_name": "Enterprise Client",
                    "customer_email": "billing@enterprise.com",
                    "customer_contact": "+919888877776",
                }
            }
        },
    }

    event_id, _, _ = provider_event_service.record_raw_event(
        db,
        razorpay_event_id=payload["id"],
        event_type=payload["event"],
        payload_json=payload,
    )

    res = provider_event_service.process_provider_event(db, event_id)
    assert res["status"] == "processed"
    case_id = res["case_id"]
    assert case_id is not None

    case = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == case_id).first()
    assert case is not None
    assert case.case_type == CaseType.OVERDUE_INVOICE.value
    assert case.origin == "live"
    assert case.amount_at_risk == 12000.0
    assert case.status == CaseStatus.DETECTED.value


def test_d3_scan_overdue_invoices_polls_gateway_api(db, monkeypatch):
    """D3: scan_overdue_invoices polls Razorpay Invoices API and creates OVERDUE_INVOICE cases."""
    def _mock_list_invoices(*args, **kwargs):
        return {
            "count": 1,
            "items": [
                {
                    "id": "inv_gateway_poll_001",
                    "amount": 450000,  # ₹4500.00
                    "currency": "INR",
                    "status": "expired",
                    "customer_name": "SaaS Subscriber",
                    "customer_email": "subscriber@saas.com",
                    "customer_contact": "+919777766665",
                }
            ],
        }

    monkeypatch.setattr("app.services.razorpay_service._list_invoices_on_gateway", _mock_list_invoices, raising=False)

    created_cases = scan_overdue_invoices(db)
    assert len(created_cases) == 1
    case = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == created_cases[0]).first()
    assert case is not None
    assert case.case_type == CaseType.OVERDUE_INVOICE.value
    assert case.origin == "live"
    assert case.amount_at_risk == 4500.0

    # Idempotent: Subsequent scan does not re-create case for same invoice
    second_run = scan_overdue_invoices(db)
    assert len(second_run) == 0


# ======================================================================================
# D4: Pipeline Segregation & Webhook Schema Validation
# ======================================================================================

def test_d4_events_detect_blocked_in_prod(client: TestClient, monkeypatch):
    """D4: HTTP self-POST detector /events/detect is blocked in production environment."""
    from app.auth import AuthContext, get_current_auth

    monkeypatch.setattr(settings, "app_env", "prod")

    fastapi_app.dependency_overrides[get_current_auth] = lambda: AuthContext(
        key_id="k_test_internal",
        name="internal_service",
        scopes={"internal"},
    )
    try:
        resp = client.post("/events/detect")
        assert resp.status_code == 403
        assert "detector is disabled in production" in resp.text.lower()
    finally:
        fastapi_app.dependency_overrides.pop(get_current_auth, None)


def test_d4_webhook_schema_validation_rejects_malformed_payload(client: TestClient):
    """D4: Webhook receiver enforces schema validation and rejects payloads missing 'event' or malformed structure."""
    malformed_payload = b'{"missing_event_field": true}'
    sig = _sign(malformed_payload)

    resp = client.post(
        "/webhooks/razorpay",
        content=malformed_payload,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert "schema" in resp.text.lower() or "missing" in resp.text.lower() or "event" in resp.text.lower()
