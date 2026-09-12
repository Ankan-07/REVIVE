from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.db import get_db
from app.schemas.job import JobRead
from app.services import job_service

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/{job_id}", response_model=JobRead, dependencies=[Depends(require_api_key("operator"))])
def get_job_endpoint(job_id: str, db: Session = Depends(get_db)):
    """Fetch status, results, and error details of a specific background job."""
    job = job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found")
    return job


@router.get("", response_model=List[JobRead], dependencies=[Depends(require_api_key("operator"))])
def list_jobs_endpoint(
    case_id: Optional[str] = Query(None, description="Filter by case ID"),
    status: Optional[str] = Query(None, description="Filter by status (QUEUED, RUNNING, COMPLETED, FAILED)"),
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List recent background jobs ordered newest first."""
    return job_service.list_jobs(
        db,
        case_id=case_id,
        status=status,
        job_type=job_type,
        skip=skip,
        limit=limit,
    )


@router.post("/verify-promises", dependencies=[Depends(require_api_key("internal"))])
def verify_promises_endpoint(db: Session = Depends(get_db)):
    """Background job trigger to verify overdue promises and escalate broken ones."""
    count = job_service.verify_overdue_promises(db)
    return {"status": "ok", "escalated_cases": count}
