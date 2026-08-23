import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db
from app.schemas.events import EventPayload, DetectionSummary
from app.services.event_service import handle_event
from app.services.detector import emit_failed_payment_events

router = APIRouter(prefix="/events", tags=["Events"])


@router.post("/")
def trigger_event(event: EventPayload, db: Session = Depends(get_db)):
    try:
        return handle_event(db, event)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/detect", response_model=DetectionSummary)
def detect_failed_payments(db: Session = Depends(get_db)):
    """Scan uncased FAILED payments and create a case for each via real `POST /events/` calls.

    The detector posts events back to this same API over HTTP (`internal_api_base_url`), so the
    server must be running to serve the nested requests. Idempotent: re-running creates no duplicates.
    """
    with httpx.Client(base_url=settings.internal_api_base_url, timeout=30.0) as client:
        summary = emit_failed_payment_events(db, client)
    return summary
