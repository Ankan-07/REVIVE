"""Comprehensive test suite for Phase B1: Razorpay Webhook Receiver.

Covers:
- B1.1: HMAC-SHA256 signature verification (valid, forged, missing secret, TLS enforcement in prod)
- B1.2: Async dispatch, fast 200-ack, race-safe deduplication via provider_events
- B1.3: Signature contract tests (offline, hermetic)
- B1.4: Refund and dispute arms (ledger reversal, case status, escalation generation)
- B1.5: Concurrent duplicate delivery race test (threadpool race condition validation)
"""
import concurrent.futures
import hashlib
import hmac
import json
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app as fastapi_app
from app.db import get_db
from app.models.case import RevenueRiskCase
from app.models.customer import Customer
from app.models.escalation import Escalation
from app.models.outcome import RecoveryOutcome
from app.models.payment import Payment
from app.models.provider_event import ProviderEvent
from app.schemas.enums import CaseStatus, OutcomeType
from app.services import outcome_service, provider_object_service

WEBHOOK_SECRET = "test_webhook_secret_xyz123"


@pytest.fixture
def db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import Base

    db_path = tmp_path / "test_webhooks.db"
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
def setup_webhook_env():
    """Ensure webhook secret is set for tests and restore afterwards."""
    orig_secret = settings.razorpay_webhook_secret
    orig_env = settings.app_env
    orig_sync = settings.sync_run_agent
    settings.razorpay_webhook_secret = WEBHOOK_SECRET
    settings.app_env = "dev"
    settings.sync_run_agent = True
    yield
    settings.razorpay_webhook_secret = orig_secret
    settings.app_env = orig_env
    settings.sync_run_agent = orig_sync


def _sign(payload_bytes: bytes, secret: str = WEBHOOK_SECRET) -> str:
    """Generate valid HMAC-SHA256 signature for a payload."""
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def test_webhook_signature_valid(client: TestClient, db):
    """B1.1, B1.3: Valid signature yields 200 OK, creates provider_events row and queues job."""
    payload = {
        "id": "evt_valid_001",
        "event": "payment_link.expired",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": "plink_test_001",
                    "status": "expired",
                }
            }
        },
    }
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(body)

    resp = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert data["event_id"] == "evt_valid_001"

    # Verify database persistence in provider_events
    evt = db.query(ProviderEvent).filter(ProviderEvent.razorpay_event_id == "evt_valid_001").first()
    assert evt is not None
    assert evt.event_type == "payment_link.expired"


def test_webhook_signature_forged(client: TestClient, db):
    """B1.1, B1.3: Forged signature yields 400 Bad Request and zero DB writes."""
    payload = {"id": "evt_forged_001", "event": "payment.failed"}
    body = json.dumps(payload).encode("utf-8")
    forged_sig = "a" * 64

    resp = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": forged_sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert "Invalid Razorpay webhook signature" in resp.json()["detail"]

    # Verify zero writes in provider_events
    evt = db.query(ProviderEvent).filter(ProviderEvent.razorpay_event_id == "evt_forged_001").first()
    assert evt is None


def test_webhook_signature_missing_secret(client: TestClient):
    """B1.1, B1.3: Missing server secret yields 400 Bad Request."""
    settings.razorpay_webhook_secret = ""
    payload = {"id": "evt_no_secret_001", "event": "payment.failed"}
    body = json.dumps(payload).encode("utf-8")

    resp = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": "dummy", "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert "Webhook verification secret is not configured" in resp.json()["detail"]


def test_webhook_replayed_event_deduplication(client: TestClient, db):
    """B1.2, B1.3: Replayed event returns already_received without creating duplicate rows/jobs."""
    payload = {
        "id": "evt_replay_test_99",
        "event": "payment_link.expired",
        "payload": {"payment_link": {"entity": {"id": "plink_replay_99"}}},
    }
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(body)

    # First delivery
    resp1 = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "queued"

    # Replayed delivery
    resp2 = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "already_received"
    assert resp2.json()["event_id"] == "evt_replay_test_99"

    # Assert exactly 1 row in provider_events
    count = db.query(ProviderEvent).filter(ProviderEvent.razorpay_event_id == "evt_replay_test_99").count()
    assert count == 1


def test_webhook_tls_enforced_in_prod(client: TestClient):
    """B1.1: Webhook enforces HTTPS when APP_ENV=prod."""
    settings.app_env = "prod"
    payload = {"id": "evt_prod_tls", "event": "payment.failed"}
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(body)

    # Plain HTTP request in prod -> rejected
    resp = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert "HTTPS connection required" in resp.json()["detail"]

    # HTTPS header (e.g. reverse proxy TLS termination) -> accepted
    resp_tls = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={
            "X-Razorpay-Signature": sig,
            "Content-Type": "application/json",
            "X-Forwarded-Proto": "https",
        },
    )
    assert resp_tls.status_code == 200


def test_webhook_concurrent_duplicate_delivery(db):
    """B1.5: Multiple concurrent threads delivering the same razorpay_event_id simultaneously.

    Asserts race safety: exactly one row in provider_events, exactly one queued job.
    """
    event_id = "evt_race_condition_test_42"
    payload = {
        "id": event_id,
        "event": "payment_link.expired",
        "payload": {"payment_link": {"entity": {"id": "plink_race_42"}}},
    }
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(body)

    def _deliver():
        c = TestClient(fastapi_app)
        return c.post(
            "/webhooks/razorpay",
            content=body,
            headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
        )

    # Run 8 concurrent delivery requests
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_deliver) for _ in range(8)]
        responses = [f.result() for f in futures]

    statuses = [r.json().get("status") for r in responses]
    assert all(r.status_code == 200 for r in responses)

    # Exactly one thread should receive 'queued'; others receive 'already_received'
    queued_count = statuses.count("queued")
    already_count = statuses.count("already_received")
    assert queued_count == 1
    assert already_count == 7

    # Verify exactly 1 database row
    event_count = db.query(ProviderEvent).filter(ProviderEvent.razorpay_event_id == event_id).count()
    assert event_count == 1


def test_webhook_payment_failed_ingestion(client: TestClient, db):
    """B1.2: payment.failed webhook creates live case and records provider object."""
    event_id = "evt_fail_ingest_001"
    pay_id = "pay_failed_live_001"
    payload = {
        "id": event_id,
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": pay_id,
                    "amount": 499900,  # 4,999 INR
                    "currency": "INR",
                    "status": "failed",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Payment was declined by issuing bank",
                    "email": "customer_live@example.com",
                    "contact": "+919876543210",
                    "notes": {"customer_name": "Priya Sharma"},
                }
            }
        },
    }
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(body)

    resp = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200

    # Verify live case created
    case = db.query(RevenueRiskCase).filter(RevenueRiskCase.payment_id == pay_id).first()
    assert case is not None
    assert case.origin == "live"
    assert case.status == CaseStatus.DETECTED.value
    assert case.amount_at_risk == 4999.0

    # Verify customer created with origin live
    cust = db.query(Customer).filter(Customer.id == case.customer_id).first()
    assert cust is not None
    assert cust.origin == "live"
    assert cust.email == "customer_live@example.com"

    # Verify provider_objects record
    pobj = provider_object_service.get_by_provider_id(db, pay_id)
    assert pobj is not None
    assert pobj.status == "failed"
    assert pobj.amount_paise == 499900


def test_webhook_payment_captured_settlement(client: TestClient, db):
    """B1.2: payment.captured webhook marks case RECOVERED and updates ledger."""
    order_id = "order_live_settle_001"
    pay_id = "pay_live_settle_001"

    # Seed an open live case
    cust = Customer(id="CUST_SETTLE_1", name="Rahul Verma", email="rahul@example.com", origin="live")
    payment = Payment(id="PAY_SETTLE_1", customer_id=cust.id, amount=3000.0, gateway="RAZORPAY", status="FAILED", origin="live")
    case = RevenueRiskCase(
        id="RR_SETTLE_1",
        customer_id=cust.id,
        payment_id=payment.id,
        case_type="FAILED_PAYMENT",
        amount_at_risk=3000.0,
        status=CaseStatus.DETECTED.value,
        origin="live",
    )
    db.add_all([cust, payment, case])
    db.commit()

    # Link order_id to case in provider_objects
    provider_object_service.record_object(
        db,
        case_id=case.id,
        object_type="order",
        provider_object_id=order_id,
        amount_paise=300000,
        status="created",
    )

    payload = {
        "id": "evt_capture_001",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": pay_id,
                    "order_id": order_id,
                    "amount": 300000,
                    "currency": "INR",
                    "status": "captured",
                    "fee": 6000,  # 60 INR
                }
            }
        },
    }
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(body)

    resp = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200

    # Refresh case & verify settlement
    db.refresh(case)
    assert case.status == CaseStatus.RECOVERED.value
    # Net recovery = 3000.0 gross - 60.0 fee (6000 paise) = 2940.0 (Phase B3.3)
    assert case.net_recovered_amount == 2940.0

    # Verify outcome row
    outcome = db.query(RecoveryOutcome).filter(RecoveryOutcome.case_id == case.id).first()
    assert outcome is not None
    assert outcome.outcome_type == OutcomeType.RECOVERED_FULL.value
    assert outcome.gross_recovered == 3000.0
    assert outcome.gateway_fee_paise == 6000
    assert outcome.net_recovered == 2940.0

    # Verify provider_objects updated
    order_obj = provider_object_service.get_by_provider_id(db, order_id)
    assert order_obj.status == "paid"

    pay_obj = provider_object_service.get_by_provider_id(db, pay_id)
    assert pay_obj.status == "captured"
    assert pay_obj.fee_paise == 6000


def test_webhook_payment_refunded_arm(client: TestClient, db):
    """B1.4: payment.refunded webhook reverses outcome, debits ledger, sets status REFUNDED."""
    pay_id = "pay_to_refund_001"
    refund_id = "rfnd_test_001"

    # Seed a settled case with outcome
    cust = Customer(id="CUST_RFND_1", name="Ananya Rao", email="ananya@example.com", origin="live")
    payment = Payment(id=pay_id, customer_id=cust.id, amount=1500.0, gateway="RAZORPAY", status="SUCCEEDED", origin="live")
    case = RevenueRiskCase(
        id="RR_RFND_1",
        customer_id=cust.id,
        payment_id=payment.id,
        case_type="FAILED_PAYMENT",
        amount_at_risk=1500.0,
        net_recovered_amount=1500.0,
        status=CaseStatus.RECOVERED.value,
        origin="live",
    )
    db.add_all([cust, payment, case])
    db.commit()

    outcome_service.record_outcome(
        db,
        case_id=case.id,
        outcome_type=OutcomeType.RECOVERED_FULL.value,
        gross_recovered=1500.0,
        cost_total=0.0,
        discount_total=0.0,
        verified=True,
    )

    provider_object_service.record_object(
        db,
        case_id=case.id,
        object_type="payment",
        provider_object_id=pay_id,
        amount_paise=150000,
        status="captured",
    )

    payload = {
        "id": "evt_refund_001",
        "event": "payment.refunded",
        "payload": {
            "refund": {
                "entity": {
                    "id": refund_id,
                    "payment_id": pay_id,
                    "amount": 150000,
                    "status": "processed",
                }
            },
            "payment": {
                "entity": {
                    "id": pay_id,
                    "amount_refunded": 150000,
                }
            },
        },
    }
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(body)

    resp = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200

    # Verify outcome reversed and case status updated
    db.refresh(case)
    assert case.status == CaseStatus.REFUNDED.value
    assert case.net_recovered_amount == 0.0

    latest_outcome = (
        db.query(RecoveryOutcome)
        .filter(RecoveryOutcome.case_id == case.id)
        .order_by(RecoveryOutcome.created_at.desc(), RecoveryOutcome.id.desc())
        .first()
    )
    assert latest_outcome.outcome_type == OutcomeType.REFUNDED.value
    assert latest_outcome.net_recovered == 0.0

    pobj = provider_object_service.get_by_provider_id(db, pay_id)
    assert pobj.status == "refunded"


def test_webhook_payment_dispute_arm(client: TestClient, db):
    """B1.4: payment.dispute.created webhook flags case DISPUTED and creates escalation row."""
    pay_id = "pay_to_dispute_001"
    dispute_id = "disp_test_001"

    # Seed a case
    cust = Customer(id="CUST_DISP_1", name="Dev Nair", email="dev@example.com", origin="live")
    payment = Payment(id=pay_id, customer_id=cust.id, amount=8000.0, gateway="RAZORPAY", status="SUCCEEDED", origin="live")
    case = RevenueRiskCase(
        id="RR_DISP_1",
        customer_id=cust.id,
        payment_id=payment.id,
        case_type="FAILED_PAYMENT",
        amount_at_risk=8000.0,
        status=CaseStatus.RECOVERED.value,
        origin="live",
    )
    db.add_all([cust, payment, case])
    db.commit()

    provider_object_service.record_object(
        db,
        case_id=case.id,
        object_type="payment",
        provider_object_id=pay_id,
        amount_paise=800000,
        status="captured",
    )

    payload = {
        "id": "evt_dispute_001",
        "event": "payment.dispute.created",
        "payload": {
            "dispute": {
                "entity": {
                    "id": dispute_id,
                    "payment_id": pay_id,
                    "amount": 800000,
                    "reason_code": "FRAUDULENT",
                    "status": "under_review",
                }
            },
            "payment": {
                "entity": {
                    "id": pay_id,
                }
            },
        },
    }
    body = json.dumps(payload).encode("utf-8")
    sig = _sign(body)

    resp = client.post(
        "/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200

    # Verify case status is DISPUTED
    db.refresh(case)
    assert case.status == CaseStatus.DISPUTED.value

    # Verify escalation row created with reason DISPUTE_FILED
    esc = db.query(Escalation).filter(Escalation.case_id == case.id).first()
    assert esc is not None
    assert esc.reason == "DISPUTE_FILED"
    assert esc.priority == "HIGH"
    assert "disp_test_001" in esc.notes


def test_webhook_hmac_failure_spike_alert(client: TestClient, db, caplog):
    """B1.1, A3.5: HMAC signature failure spikes are logged with SECURITY ALERT."""
    import logging

    payload = json.dumps({"id": "evt_fail_burst", "event": "payment.failed"}).encode("utf-8")
    forged_sig = "bad_sig_123"

    with caplog.at_level(logging.CRITICAL):
        for i in range(11):
            resp = client.post(
                "/webhooks/razorpay",
                content=payload,
                headers={"X-Razorpay-Signature": forged_sig, "Content-Type": "application/json"},
            )
            assert resp.status_code == 400

    # Verify that SECURITY ALERT was triggered in log output
    assert any("[SECURITY ALERT] Razorpay webhook HMAC failure spike" in record.message for record in caplog.records)
