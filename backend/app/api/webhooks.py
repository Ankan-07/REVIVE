"""Razorpay Webhook receiver (PRD §38, Phase B1).

Source of truth for live payment events:
- payment.failed
- payment.captured / payment_link.paid
- payment.refunded
- payment.dispute.created
- payment_link.expired
- invoice.expired

Hardened with:
- Raw body HMAC-SHA256 signature verification with timing-safe comparison (B1.1)
- Sliding-window HMAC failure metric tracking and alerting (B1.1, A3.5)
- TLS enforcement in production environments (B1.1)
- Fast 200-ack with synchronous deduplication via UNIQUE razorpay_event_id (B1.2)
- Asynchronous worker dispatch via Redis+ARQ with sync/background fallback (B1.2)
"""
import hashlib
import hmac
import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_db
from app.jobs.client import enqueue_job
from app.services import job_service, provider_event_service

logger = logging.getLogger("revive.webhooks")

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def _run_sync_event_processing(event_id: str, job_id: str) -> None:
    """Fallback runner for synchronous test / local development mode."""
    db = SessionLocal()
    try:
        job_service.mark_running(db, job_id)
        res = provider_event_service.process_provider_event(db, event_id=event_id)
        job_service.mark_completed(db, job_id, result=res)
    except Exception as exc:
        job_service.mark_failed(db, job_id, error_message=str(exc))
    finally:
        db.close()


@router.post("/razorpay", status_code=status.HTTP_200_OK)
async def receive_razorpay_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_razorpay_signature: str = Header(None, alias="X-Razorpay-Signature"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Receive, verify, deduplicate, and enqueue incoming Razorpay webhooks."""
    client_ip = request.client.host if request.client else "unknown"

    # 1. Enforce TLS in production (B1.1)
    if settings.app_env.lower() == "prod":
        is_https = (
            request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").lower() == "https"
        )
        if not is_https:
            provider_event_service.record_hmac_failure(
                db, reason="non_https_production_request", client_ip=client_ip
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="HTTPS connection required for production webhooks.",
            )

    # 2. Read raw request body
    raw_body = await request.body()
    if not raw_body:
        provider_event_service.record_hmac_failure(
            db, reason="empty_webhook_body", client_ip=client_ip
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty webhook body.",
        )

    # 3. Verify HMAC signature (B1.1)
    secret = settings.razorpay_webhook_secret
    if not secret:
        provider_event_service.record_hmac_failure(
            db, reason="missing_server_webhook_secret", client_ip=client_ip
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook verification secret is not configured.",
        )

    if not x_razorpay_signature:
        provider_event_service.record_hmac_failure(
            db, reason="missing_x_razorpay_signature", client_ip=client_ip
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Razorpay-Signature header.",
        )

    expected_sig = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, x_razorpay_signature):
        provider_event_service.record_hmac_failure(
            db, reason="invalid_hmac_signature", client_ip=client_ip
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Razorpay webhook signature.",
        )

    # 4. Parse JSON payload
    try:
        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed JSON payload: {exc}",
        )

    # 4.1 Schema validation (Phase D4)
    event_type = payload.get("event")
    if not event_type or not isinstance(event_type, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook schema validation failed: missing or invalid 'event' field.",
        )

    # 5. Extract event identifiers
    event_id = payload.get("id") or payload.get("event_id")
    if not event_id:
        # Fallback to deterministic SHA-256 hash of raw body if provider event id is omitted
        event_id = f"evt_{hashlib.sha256(raw_body).hexdigest()[:24]}"

    # 6. Race-safe synchronous deduplication (B1.2)
    event_pk_id, is_new, is_processed = provider_event_service.record_raw_event(
        db,
        provider="razorpay",
        razorpay_event_id=event_id,
        event_type=event_type,
        payload_json=payload,
    )

    if not is_new:
        return {
            "status": "already_received",
            "event_id": event_id,
            "processed": is_processed,
        }

    # 7. Fast 200-ack + Asynchronous dispatch (B1.2)
    job = job_service.create_job(
        db,
        job_type="process_webhook_event",
        payload={"event_id": event_pk_id, "razorpay_event_id": event_id},
    )

    if not settings.sync_run_agent:
        try:
            await enqueue_job("process_webhook_event_job", event_pk_id, job_id=job.id)
        except Exception as exc:
            logger.warning(
                f"ARQ queue unreachable for webhook {event_id} ({exc}); falling back to background task."
            )
            background_tasks.add_task(_run_sync_event_processing, event_pk_id, job.id)
    else:
        # Development / test profile: run via background task
        background_tasks.add_task(_run_sync_event_processing, event_pk_id, job.id)

    return {
        "status": "queued",
        "event_id": event_id,
        "job_id": job.id,
    }
