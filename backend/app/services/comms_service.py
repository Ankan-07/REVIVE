"""Communications service for processing inbound replies and promise tracking (Phase C)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.db import utc_now
from app.domain.ids import generate_id
from app.models.case import RevenueRiskCase
from app.models.communication import Communication
from app.models.promise import PromiseToPay
from app.observability import traceable
from app.schemas.enums import PromiseStatus


def _extract_promise_date(text: str) -> Optional[datetime]:
    """Safely extract ISO YYYY-MM-DD date and validate against injection / bounds."""
    if not text or not isinstance(text, str):
        return None

    # Check for basic prompt injection phrases attempting to override controls
    lowered = text.lower()
    if "override" in lowered and "ignore" in lowered:
        return None

    # Look for ISO date patterns (YYYY-MM-DD)
    match = re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b", text)
    if not match:
        return None

    date_str = match.group(0)
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None

    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    max_allowed = today_start + timedelta(days=90)

    # Must not be in the past, and within 90 days
    if parsed < today_start or parsed > max_allowed:
        return None

    return parsed


@traceable(name="service.comms.record_inbound_reply", run_type="chain")
def record_inbound_reply(
    db: Session,
    *,
    communication_id: str,
    reply_body: str,
) -> Optional[PromiseToPay]:
    """Record customer inbound reply, extract promise to pay date, and track promise."""
    comm = db.query(Communication).filter(Communication.id == communication_id).first()
    if not comm:
        return None

    comm.reply_body = reply_body
    db.flush()

    target_date = _extract_promise_date(reply_body)
    if not target_date:
        db.commit()
        return None

    case = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == comm.case_id).first()
    amount = case.amount_at_risk if case else 0.0

    promise_id = generate_id("P2P", db)
    promise = PromiseToPay(
        id=promise_id,
        case_id=comm.case_id,
        customer_id=comm.customer_id,
        promised_amount=amount,
        promised_date=target_date,
        status=PromiseStatus.PENDING.value,
        created_at=utc_now(),
    )
    db.add(promise)
    db.commit()
    db.refresh(promise)
    return promise
