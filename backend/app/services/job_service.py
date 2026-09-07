from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.audit import recorder
from app.models.case import RevenueRiskCase
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

    # Join so we can filter on the case's status and update both rows without a second query.
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
        # recorder.record commits, so each promise + case status lands with its audit event.
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
