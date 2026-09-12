"""Job service managing background task lifecycle and dead-letter visibility (Phase A4)."""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.audit import recorder
from app.db import utc_now
from app.models.case import RevenueRiskCase
from app.models.job import Job
from app.models.promise import PromiseToPay
from app.schemas.enums import CaseStatus, PromiseStatus


def verify_overdue_promises(db: Session) -> int:
    """Finds PENDING promises whose date has passed on cases that aren't already closed or recovered.

    Marks them BROKEN, escalates the case, and appends a ``PROMISE_BROKEN`` audit event for each.
    Returns the number of promises that were escalated.
    """
    now = datetime.now(timezone.utc)
    closed_statuses = [
        CaseStatus.RECOVERED.value,
        CaseStatus.CLOSED_NO_RECOVERY.value,
        CaseStatus.EXPIRED.value,
    ]

    overdue_rows = (
        db.query(PromiseToPay, RevenueRiskCase)
        .join(RevenueRiskCase, RevenueRiskCase.id == PromiseToPay.case_id)
        .filter(
            PromiseToPay.status == PromiseStatus.PENDING.value,
            PromiseToPay.promised_date < now,
            RevenueRiskCase.status.notin_(closed_statuses),
        )
        .all()
    )

    count = 0
    for promise, case in overdue_rows:
        promise.status = PromiseStatus.BROKEN.value
        case.status = CaseStatus.ESCALATED.value
        recorder.record(
            db,
            case.id,
            "PROMISE_BROKEN",
            payload={
                "promise_id": promise.id,
                "promised_date": promise.promised_date.isoformat(),
            },
            actor="system",
        )
        count += 1

    return count


def create_job(
    db: Session,
    job_type: str,
    case_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    job_id: Optional[str] = None,
    max_retries: int = 3,
) -> Job:
    """Create a new job row in QUEUED status."""
    jid = job_id or str(uuid.uuid4())
    job = Job(
        id=jid,
        job_type=job_type,
        status="QUEUED",
        case_id=case_id,
        payload_json=payload or {},
        result_json=None,
        error_message=None,
        traceback=None,
        retry_count=0,
        max_retries=max_retries,
        created_at=utc_now(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def mark_running(db: Session, job_id: str) -> Optional[Job]:
    """Transition job status to RUNNING and record started_at timestamp."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        return None
    job.status = "RUNNING"
    job.started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return job


def mark_completed(db: Session, job_id: str, result: Optional[Dict[str, Any]] = None) -> Optional[Job]:
    """Transition job status to COMPLETED, store result payload, and record completed_at."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        return None
    job.status = "COMPLETED"
    job.completed_at = datetime.now(timezone.utc)
    if result is not None:
        job.result_json = result
    db.commit()
    db.refresh(job)
    return job


def mark_failed(
    db: Session,
    job_id: str,
    error_message: str,
    traceback_str: Optional[str] = None,
    increment_retry: bool = False,
) -> Optional[Job]:
    """Record job failure with error message and full traceback (dead-letter visibility)."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        return None
    if increment_retry:
        job.retry_count += 1
    job.status = "FAILED"
    job.completed_at = datetime.now(timezone.utc)
    job.error_message = error_message
    job.traceback = traceback_str
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: str) -> Optional[Job]:
    """Fetch a single job record by ID."""
    return db.query(Job).filter(Job.id == job_id).first()


def list_jobs(
    db: Session,
    case_id: Optional[str] = None,
    status: Optional[str] = None,
    job_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[Job]:
    """List jobs filtered by case, status, or job_type, ordered newest first."""
    query = db.query(Job)
    if case_id:
        query = query.filter(Job.case_id == case_id)
    if status:
        query = query.filter(Job.status == status)
    if job_type:
        query = query.filter(Job.job_type == job_type)
    return query.order_by(desc(Job.created_at)).offset(skip).limit(limit).all()


def get_last_completed_job_by_type(db: Session, job_type: str) -> Optional[Job]:
    """Get the most recently completed job of a given type (used for missed-run catch-up)."""
    return (
        db.query(Job)
        .filter(Job.job_type == job_type, Job.status == "COMPLETED")
        .order_by(desc(Job.completed_at))
        .first()
    )
