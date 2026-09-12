from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.auth import require_api_key
from app.db import get_db
from app.services import job_service

router = APIRouter(prefix="/jobs", tags=["Jobs"], dependencies=[Depends(require_api_key("internal"))])

@router.post("/verify-promises")
def verify_promises_endpoint(db: Session = Depends(get_db)):
    """Background job trigger to verify overdue promises and escalate broken ones."""
    count = job_service.verify_overdue_promises(db)
    return {"status": "ok", "escalated_cases": count}
