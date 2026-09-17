"""Case run lock service (Phase B4.3).

Per-case execution registry and distributed concurrency control.
Prevents duplicate LangGraph runs, race conditions between webhooks and
operator escalation resolves, and handles stale lock reclamation.
"""
import uuid
import logging
from datetime import timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.db import utc_now
from app.models.case_run_lock import CaseRunLock

logger = logging.getLogger("revive.case_run_locks")


def get_lock(db: Session, case_id: str) -> Optional[CaseRunLock]:
    """Retrieve current lock status for a case."""
    return db.query(CaseRunLock).filter(CaseRunLock.case_id == case_id).first()


def acquire_lock(
    db: Session,
    case_id: str,
    job_id: Optional[str] = None,
    timeout_seconds: int = 300,
) -> Tuple[bool, Optional[str], Optional[CaseRunLock]]:
    """Attempt to acquire the execution lock for a given case.

    Returns:
        (acquired: bool, reason: Optional[str], lock: Optional[CaseRunLock])
    """
    now = utc_now()
    token = str(uuid.uuid4())

    # Check for existing lock with row lock if possible
    query = db.query(CaseRunLock).filter(CaseRunLock.case_id == case_id)
    try:
        query = query.with_for_update()
    except Exception:
        # SQLite in-memory or fallback without FOR UPDATE support
        pass

    lock = query.first()

    if lock is None:
        lock = CaseRunLock(
            id=f"LCK-{uuid.uuid4().hex[:12]}",
            case_id=case_id,
            state="running",
            locked_at=now,
            locked_by_job_id=job_id,
            lock_token=token,
            created_at=now,
            updated_at=now,
        )
        try:
            db.add(lock)
            db.commit()
            db.refresh(lock)
            return True, None, lock
        except IntegrityError:
            db.rollback()
            # Race condition: someone inserted right before us
            lock = db.query(CaseRunLock).filter(CaseRunLock.case_id == case_id).first()
            if not lock:
                return False, "concurrent_insert_failed", None

    if lock.state == "terminal":
        return False, "terminal", lock

    if lock.state == "running":
        # Check if lock has timed out (stale execution / crashed worker)
        locked_at = lock.locked_at
        if locked_at is not None:
            if locked_at.tzinfo is None:
                locked_at = locked_at.replace(tzinfo=timezone.utc)
            elapsed = (now - locked_at).total_seconds()
            if elapsed > timeout_seconds:
                logger.warning(
                    f"Reclaiming stale lock on case {case_id} (held for {elapsed:.1f}s > {timeout_seconds}s)"
                )
                lock.state = "running"
                lock.locked_at = now
                lock.locked_by_job_id = job_id
                lock.lock_token = token
                lock.updated_at = now
                db.commit()
                db.refresh(lock)
                return True, "stale_reclaimed", lock

        return False, "already_running", lock

    # State is 'released' or 'queued'
    lock.state = "running"
    lock.locked_at = now
    lock.locked_by_job_id = job_id
    lock.lock_token = token
    lock.updated_at = now
    db.commit()
    db.refresh(lock)
    return True, None, lock


def release_lock(db: Session, case_id: str, terminal: bool = False) -> Optional[CaseRunLock]:
    """Release the execution lock for a given case, setting state to terminal or released."""
    now = utc_now()
    lock = db.query(CaseRunLock).filter(CaseRunLock.case_id == case_id).first()
    if lock:
        lock.state = "terminal" if terminal else "released"
        lock.locked_by_job_id = None
        lock.updated_at = now
        db.commit()
        db.refresh(lock)
    return lock
