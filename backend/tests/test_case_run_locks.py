"""Tests for Phase B4.3: Per-case run registry and concurrency control (case_run_locks)."""
import threading
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from langgraph.checkpoint.memory import MemorySaver

from app.agent.runner import run_agent, resume_agent
from app.db import Base
from app.models.case import RevenueRiskCase
from app.models.customer import Customer
from app.models.payment import Payment
from app.schemas.enums import CaseStatus, CaseType
from app.services import case_run_lock_service, escalation_service


import uuid

@pytest.fixture
def factory():
    db_id = uuid.uuid4().hex
    engine = create_engine(
        f"sqlite:///file:memdb_{db_id}?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )
    Base.metadata.create_all(bind=engine)
    conn = engine.connect()
    maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield maker
    conn.close()


@pytest.fixture
def db(factory):
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def checkpointer():
    return MemorySaver()


def _seed_case(db, case_id="RR-LOCK-TEST", amount=5000.0):
    cust = Customer(id=f"CUS-{case_id}", name="Lock Customer", email="lock@example.com", origin="live")
    pay = Payment(id=f"PAY-{case_id}", customer_id=cust.id, amount=amount, status="FAILED", gateway="RAZORPAY")
    case = RevenueRiskCase(
        id=case_id,
        customer_id=cust.id,
        payment_id=pay.id,
        case_type=CaseType.FAILED_PAYMENT.value,
        origin="live",
        status=CaseStatus.DETECTED.value,
        amount_at_risk=amount,
    )
    db.add(cust)
    db.add(pay)
    db.add(case)
    db.commit()
    return case


def test_lock_acquire_and_release(db):
    case = _seed_case(db, "RR-LOCK-1")

    # 1. Acquire lock
    acquired, reason, lock = case_run_lock_service.acquire_lock(db, case.id, job_id="job_001")
    assert acquired is True
    assert reason is None
    assert lock.state == "running"
    assert lock.locked_by_job_id == "job_001"

    # 2. Second acquire fails while lock is held
    acq2, reason2, _ = case_run_lock_service.acquire_lock(db, case.id, job_id="job_002")
    assert acq2 is False
    assert reason2 == "already_running"

    # 3. Release lock
    case_run_lock_service.release_lock(db, case.id, terminal=False)
    lock_released = case_run_lock_service.get_lock(db, case.id)
    assert lock_released.state == "released"

    # 4. Acquire again succeeds
    acq3, reason3, lock3 = case_run_lock_service.acquire_lock(db, case.id, job_id="job_003")
    assert acq3 is True
    assert lock3.state == "running"

    # 5. Terminal release
    case_run_lock_service.release_lock(db, case.id, terminal=True)
    lock_term = case_run_lock_service.get_lock(db, case.id)
    assert lock_term.state == "terminal"

    # 6. Terminal lock cannot be acquired
    acq4, reason4, _ = case_run_lock_service.acquire_lock(db, case.id)
    assert acq4 is False
    assert reason4 == "terminal"


def test_stale_lock_reclamation(db):
    case = _seed_case(db, "RR-LOCK-STALE")

    # Acquire initial lock
    case_run_lock_service.acquire_lock(db, case.id, job_id="crashed_job")
    lock = case_run_lock_service.get_lock(db, case.id)

    # Manually backdate locked_at by 10 minutes (600s > 300s timeout)
    lock.locked_at = datetime.now(timezone.utc) - timedelta(seconds=600)
    db.commit()

    # Next caller should safely reclaim the stale lock
    acquired, reason, lock = case_run_lock_service.acquire_lock(db, case.id, job_id="new_job", timeout_seconds=300)
    assert acquired is True
    assert reason == "stale_reclaimed"
    assert lock.locked_by_job_id == "new_job"


def test_concurrent_escalation_resolutions_are_idempotent(factory, db, checkpointer):
    """Two threads resolving the same escalation simultaneously -> one wins, other is idempotent."""
    case = _seed_case(db, "RR-CONCURRENT-ESC", amount=150000.0)

    # 1. Run agent: pauses at escalation_pause and creates escalation ticket + checkpoint
    res = run_agent(case.id, session_factory=factory, checkpointer=checkpointer)
    assert res.get("terminal_status") is None

    db.expire_all()
    esc = escalation_service.get_open_for_case(db, case.id)
    assert esc is not None
    assert esc.status == "OPEN"

    results = []
    errors = []

    def _worker(thread_idx):
        s = factory()
        try:
            res_esc, transitioned = escalation_service.resolve_escalation(
                s, esc.id, resolution_status="APPROVED", notes=f"Resolved by thread {thread_idx}"
            )
            if transitioned:
                # Winner invokes resume_agent
                r = resume_agent(case.id, resolution="APPROVED", session_factory=factory, checkpointer=checkpointer)
                results.append(("winner", thread_idx, r))
            else:
                # Loser receives idempotent state without duplicate invocation
                results.append(("loser", thread_idx, None))
        except Exception as exc:
            errors.append(exc)
        finally:
            s.close()

    t1 = threading.Thread(target=_worker, args=(1,))
    t2 = threading.Thread(target=_worker, args=(2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(errors) == 0, f"Concurrent execution generated errors: {errors}"
    assert len(results) == 2

    # Exactly one winner, exactly one loser
    statuses = [r[0] for r in results]
    assert statuses.count("winner") == 1
    assert statuses.count("loser") == 1

    # Final escalation status is APPROVED
    db.expire_all()
    final_esc = escalation_service.get_escalation(db, esc.id)
    assert final_esc.status == "APPROVED"
