"""Authenticated HTTP Cron Trigger Router (Phase G1 / Serverless Cron).

Exposes secure endpoints callable by GitHub Actions or external schedulers to
trigger recovery scans, reconciliation audits, and timeout processors on free-tier
or serverless environments without requiring a 24/7 background worker process.
"""
from __future__ import annotations

import hmac
import logging
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db, get_session_factory
from app.jobs.worker import (
    abandonment_scan_job,
    check_outcome_timeouts_job,
    invoice_scan_job,
    reconcile_job,
    verify_promises_job,
)
from app.services import api_key_service

logger = logging.getLogger("revive.cron")

router = APIRouter(prefix="/cron", tags=["Serverless Cron"])


def get_cron_auth(
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> bool:
    """Verify that the caller is authorized to trigger cron tasks.

    Accepts:
    1. X-Cron-Secret header matching settings.cron_secret.
    2. Authorization: Bearer <secret> matching settings.cron_secret or valid admin API key.
    3. X-API-Key header matching valid admin or system API key.
    """
    token: Optional[str] = None

    if x_cron_secret:
        token = x_cron_secret.strip()
    elif authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    elif x_api_key:
        token = x_api_key.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing cron authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 1. Match against configured CRON_SECRET
    configured_secret = getattr(settings, "cron_secret", None)
    if configured_secret and hmac.compare_digest(token, configured_secret):
        return True

    # 2. Fallback: match against valid API key with admin/system scope
    try:
        key_record = api_key_service.verify_api_key(db, token)
        if key_record and not key_record.revoked:
            scopes = set(s.strip() for s in (key_record.scopes or "").split(",") if s.strip())
            if "admin" in scopes or "system" in scopes:
                return True
    except Exception as e:
        logger.debug(f"API key fallback check failed in cron auth: {e}")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid cron authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/abandonment-scan")
async def trigger_abandonment_scan(
    _: bool = Depends(get_cron_auth),
    factory: Callable[[], Session] = Depends(get_session_factory),
) -> Dict[str, Any]:
    """Trigger abandonment scan for incomplete checkouts and expired payment links."""
    ctx = {"session_factory": factory}
    res = await abandonment_scan_job(ctx)
    return res


@router.post("/invoice-scan")
async def trigger_invoice_scan(
    _: bool = Depends(get_cron_auth),
    factory: Callable[[], Session] = Depends(get_session_factory),
) -> Dict[str, Any]:
    """Trigger invoice scan for overdue Razorpay invoices."""
    ctx = {"session_factory": factory}
    res = await invoice_scan_job(ctx)
    if "invoices_detected" not in res:
        res["invoices_detected"] = res.get("overdue_detected", 0)
    return res


@router.post("/verify-promises")
async def trigger_verify_promises(
    _: bool = Depends(get_cron_auth),
    factory: Callable[[], Session] = Depends(get_session_factory),
) -> Dict[str, Any]:
    """Trigger verification of overdue promises to pay."""
    ctx = {"session_factory": factory}
    res = await verify_promises_job(ctx)
    return res


@router.post("/reconcile")
async def trigger_reconcile(
    _: bool = Depends(get_cron_auth),
    factory: Callable[[], Session] = Depends(get_session_factory),
) -> Dict[str, Any]:
    """Trigger ledger reconciliation audit and escalation SLA breach checks."""
    ctx = {"session_factory": factory}
    res = await reconcile_job(ctx)
    return res


@router.post("/outcome-timeouts")
async def trigger_outcome_timeouts(
    _: bool = Depends(get_cron_auth),
    factory: Callable[[], Session] = Depends(get_session_factory),
) -> Dict[str, Any]:
    """Trigger outcome timeout checks for waiting cases."""
    ctx = {"session_factory": factory}
    res = await check_outcome_timeouts_job(ctx)
    return {
        "status": "completed",
        "job_type": "check_outcome_timeouts_job",
        "cases_checked": res.get("cases_checked", 0),
        "resumed_count": res.get("resumed_count", 0),
        "timed_out_count": res.get("resumed_count", 0),
        "wait_hours": res.get("wait_hours", 0),
    }


@router.post("/tick")
async def trigger_unified_tick(
    _: bool = Depends(get_cron_auth),
    factory: Callable[[], Session] = Depends(get_session_factory),
) -> Dict[str, Any]:
    """Unified runner for routine hourly checks.

    Runs abandonment scan, invoice scan, verify promises, and outcome timeouts
    sequentially in a single HTTP request to save GitHub Actions runner minutes.
    """
    ctx = {"session_factory": factory}

    abandonment_res = await abandonment_scan_job(ctx)
    invoice_res = await invoice_scan_job(ctx)
    promises_res = await verify_promises_job(ctx)
    timeouts_res = await check_outcome_timeouts_job(ctx)

    return {
        "status": "completed",
        "job_type": "unified_tick",
        "jobs": {
            "abandonment_scan": abandonment_res,
            "invoice_scan": invoice_res,
            "verify_promises": promises_res,
            "outcome_timeouts": timeouts_res,
        },
    }
