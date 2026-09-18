"""Tests for authenticated cron trigger endpoints (Phase G1 / Serverless Cron).

Covers:
- Rejection of unauthenticated requests (401).
- Rejection of invalid secrets (401).
- Successful execution of abandonment scan via POST /cron/abandonment-scan.
- Successful execution of invoice scan via POST /cron/invoice-scan.
- Successful execution of promise verification via POST /cron/verify-promises.
- Successful execution of reconciliation via POST /cron/reconcile.
- Successful execution of outcome timeouts via POST /cron/outcome-timeouts.
- Successful execution of unified tick via POST /cron/tick.
"""
from typing import Generator
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db, get_session_factory
from app.main import app
from app.config import settings


@pytest.fixture
def cron_test_client() -> Generator[TestClient, None, None]:
    """Test environment with in-memory DB and configured cron secret."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_factory] = lambda: TestingSessionLocal

    orig_secret = getattr(settings, "cron_secret", None)
    settings.cron_secret = "test-cron-secret-12345"

    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        settings.cron_secret = orig_secret


def test_cron_endpoints_require_auth(cron_test_client: TestClient) -> None:
    """Requests without auth header should be rejected with 401."""
    res = cron_test_client.post("/cron/abandonment-scan")
    assert res.status_code == 401

    res = cron_test_client.post("/cron/abandonment-scan", headers={"X-Cron-Secret": "wrong-secret"})
    assert res.status_code == 401

    res = cron_test_client.post("/cron/tick", headers={"Authorization": "Bearer wrong-secret"})
    assert res.status_code == 401


def test_cron_abandonment_scan(cron_test_client: TestClient) -> None:
    """POST /cron/abandonment-scan with valid secret runs scan and returns 200."""
    with patch("app.services.detection_service.scan_abandoned_checkouts", return_value=["case_abc_1"]):
        res = cron_test_client.post(
            "/cron/abandonment-scan",
            headers={"X-Cron-Secret": "test-cron-secret-12345"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert data["job_type"] == "abandonment_scan_job"
        assert data["abandoned_detected"] == 1
        assert "case_abc_1" in data["created_case_ids"]


def test_cron_invoice_scan(cron_test_client: TestClient) -> None:
    """POST /cron/invoice-scan with Bearer auth runs scan and returns 200."""
    with patch("app.services.detection_service.scan_overdue_invoices", return_value=["case_inv_1"]):
        res = cron_test_client.post(
            "/cron/invoice-scan",
            headers={"Authorization": "Bearer test-cron-secret-12345"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert data["job_type"] == "invoice_scan_job"
        assert data["invoices_detected"] == 1


def test_cron_verify_promises(cron_test_client: TestClient) -> None:
    """POST /cron/verify-promises evaluates overdue promises."""
    with patch("app.services.job_service.verify_overdue_promises", return_value=3):
        res = cron_test_client.post(
            "/cron/verify-promises",
            headers={"X-Cron-Secret": "test-cron-secret-12345"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert data["evaluated_count"] == 3


def test_cron_reconcile(cron_test_client: TestClient) -> None:
    """POST /cron/reconcile runs reconciliation and SLA checks."""
    mock_report = {"status": "reconciled", "total_checked": 5, "matched": 5, "mismatches": 0}
    with patch("app.services.reconciliation_service.reconcile_all", return_value=mock_report), \
         patch("app.services.reconciliation_service.check_escalation_slas", return_value=[]):
        res = cron_test_client.post(
            "/cron/reconcile",
            headers={"X-Cron-Secret": "test-cron-secret-12345"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert data["mismatches_found"] == 0
        assert data["aging_escalations_count"] == 0


def test_cron_outcome_timeouts(cron_test_client: TestClient) -> None:
    """POST /cron/outcome-timeouts checks outcome timeouts."""
    with patch("app.api.cron.check_outcome_timeouts_job", return_value={"cases_checked": 2, "resumed_count": 2, "wait_hours": 24}):
        res = cron_test_client.post(
            "/cron/outcome-timeouts",
            headers={"X-Cron-Secret": "test-cron-secret-12345"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert data["timed_out_count"] == 2


def test_cron_tick_unified(cron_test_client: TestClient) -> None:
    """POST /cron/tick runs all hourly routine jobs in sequence."""
    with patch("app.services.detection_service.scan_abandoned_checkouts", return_value=[]), \
         patch("app.services.detection_service.scan_overdue_invoices", return_value=[]), \
         patch("app.services.job_service.verify_overdue_promises", return_value=0), \
         patch("app.api.cron.check_outcome_timeouts_job", return_value={"cases_checked": 0, "resumed_count": 0, "wait_hours": 24}):
        res = cron_test_client.post(
            "/cron/tick",
            headers={"X-Cron-Secret": "test-cron-secret-12345"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert "abandonment_scan" in data["jobs"]
        assert "invoice_scan" in data["jobs"]
        assert "verify_promises" in data["jobs"]
        assert "outcome_timeouts" in data["jobs"]
