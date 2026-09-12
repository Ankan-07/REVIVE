"""Tests for background jobs, ARQ worker tasks, and async execution (Phase A4)."""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db, get_session_factory
from app.main import app
from app.models.case import RevenueRiskCase
from app.models.customer import Customer
from app.schemas.enums import CaseStatus, CaseType, Priority
from app.services import job_service


@pytest.fixture
def jobs_test_env():
    """Sets up an isolated in-memory database and test client for jobs."""
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

    session = TestingSessionLocal()
    # Seed a test customer and case
    cust = Customer(id="cust_test_job", name="Test User", email="test@example.com")
    session.add(cust)
    session.commit()

    case = RevenueRiskCase(
        id="case_job_1",
        customer_id="cust_test_job",
        case_type=CaseType.FAILED_PAYMENT.value,
        status=CaseStatus.DETECTED.value,
        amount_at_risk=5000.0,
        priority=Priority.MEDIUM.value,
        risk_score=0.5,
    )
    session.add(case)
    session.commit()

    client = TestClient(app)

    yield {
        "client": client,
        "session": session,
        "session_factory": TestingSessionLocal,
        "case_id": "case_job_1",
    }

    app.dependency_overrides.clear()
    session.close()


def test_job_service_lifecycle(jobs_test_env):
    """Test standard job transitions: QUEUED -> RUNNING -> COMPLETED."""
    db = jobs_test_env["session"]
    case_id = jobs_test_env["case_id"]

    # 1. Create Job (QUEUED)
    job = job_service.create_job(db, job_type="run_agent", case_id=case_id, payload={"test": True})
    assert job.id is not None
    assert job.status == "QUEUED"
    assert job.job_type == "run_agent"
    assert job.case_id == case_id
    assert job.started_at is None
    assert job.completed_at is None

    # 2. Mark Running
    running_job = job_service.mark_running(db, job.id)
    assert running_job is not None
    assert running_job.status == "RUNNING"
    assert running_job.started_at is not None

    # 3. Mark Completed
    completed_job = job_service.mark_completed(db, job.id, result={"recovered": True, "amount": 5000.0})
    assert completed_job is not None
    assert completed_job.status == "COMPLETED"
    assert completed_job.completed_at is not None
    assert completed_job.result_json == {"recovered": True, "amount": 5000.0}


def test_job_service_dead_letter_failure_logging(jobs_test_env):
    """Test that failed jobs record full error message and traceback for dead-letter visibility (A4.4)."""
    db = jobs_test_env["session"]

    job = job_service.create_job(db, job_type="reconcile_job")
    job_service.mark_running(db, job.id)

    dummy_traceback = "Traceback (most recent call last):\n  File 'test.py', line 10, in run\nValueError: Connection refused"
    failed_job = job_service.mark_failed(
        db,
        job.id,
        error_message="ValueError: Connection refused",
        traceback_str=dummy_traceback,
        increment_retry=True,
    )

    assert failed_job is not None
    assert failed_job.status == "FAILED"
    assert failed_job.retry_count == 1
    assert failed_job.error_message == "ValueError: Connection refused"
    assert failed_job.traceback == dummy_traceback
    assert failed_job.completed_at is not None


def test_get_job_endpoint(jobs_test_env):
    """Test GET /jobs/{job_id} endpoint."""
    client = jobs_test_env["client"]
    db = jobs_test_env["session"]

    job = job_service.create_job(db, job_type="abandonment_scan", payload={"threshold": 24})
    job_service.mark_completed(db, job.id, result={"scanned": 10, "abandoned": 2})

    res = client.get(f"/jobs/{job.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == job.id
    assert data["job_type"] == "abandonment_scan"
    assert data["status"] == "COMPLETED"
    assert data["result_json"]["scanned"] == 10

    # Non-existent job
    res_404 = client.get("/jobs/non-existent-uuid")
    assert res_404.status_code == 404


def test_list_jobs_endpoint(jobs_test_env):
    """Test GET /jobs endpoint with filters."""
    client = jobs_test_env["client"]
    db = jobs_test_env["session"]

    j1 = job_service.create_job(db, job_type="run_agent", case_id="case_job_1")
    job_service.create_job(db, job_type="reconcile_job")
    job_service.mark_completed(db, j1.id)

    # Filter by job_type
    res = client.get("/jobs?job_type=reconcile_job")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    assert all(j["job_type"] == "reconcile_job" for j in data)

    # Filter by status
    res = client.get("/jobs?status=COMPLETED")
    assert res.status_code == 200
    data = res.json()
    assert any(j["id"] == j1.id for j in data)


def test_run_agent_async_202_accepted(jobs_test_env):
    """Test that POST /cases/{id}/run-agent in async mode returns HTTP 202 Accepted with job_id."""
    client = jobs_test_env["client"]
    case_id = jobs_test_env["case_id"]

    # Mock enqueue_job so we don't require an active Redis daemon during unit tests
    with patch("app.api.cases.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        mock_enqueue.return_value = "mock_arq_job_id"

        # Request async execution via sync=false query param
        res = client.post(f"/cases/{case_id}/run-agent?sync=false")
        assert res.status_code == 202
        body = res.json()

        assert "job_id" in body
        assert body["status"] == "QUEUED"
        assert body["status_url"] == f"/jobs/{body['job_id']}"
        assert body["case_id"] == case_id

        mock_enqueue.assert_awaited_once()


def test_run_agent_sync_fallback_200(jobs_test_env):
    """Test that POST /cases/{id}/run-agent with sync=true executes synchronously and returns 200."""
    client = jobs_test_env["client"]
    case_id = jobs_test_env["case_id"]

    # With sync=true, it runs synchronously
    res = client.post(f"/cases/{case_id}/run-agent?sync=true")
    assert res.status_code == 200
    body = res.json()
    assert body["case_id"] == case_id
    assert "status" in body
    assert "timeline" in body


def test_missed_run_catchup_detection(jobs_test_env):
    """Test that get_last_completed_job_by_type identifies stale runs for startup catch-up (A4.4)."""
    db = jobs_test_env["session"]

    # No completed job initially
    last = job_service.get_last_completed_job_by_type(db, "reconcile_job")
    assert last is None

    # Complete a job
    job = job_service.create_job(db, job_type="reconcile_job")
    job_service.mark_completed(db, job.id, result={"status": "ok"})

    last = job_service.get_last_completed_job_by_type(db, "reconcile_job")
    assert last is not None
    assert last.id == job.id
