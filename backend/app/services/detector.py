"""Failed-payment detector (Phase 3 · PRD §5, §8).

Scans the payments table for `FAILED` payments that do not yet have a `RevenueRiskCase`, and drives
each one into a case by POSTing a `PAYMENT_FAILED` event to the real `/events/` HTTP endpoint. This
is the seam between the seeded simulator (which only writes payment rows) and the event pipeline
(which creates cases): simulated failures become workable cases without any manual event posting.

The HTTP `client` is injected and duck-typed -- anything with `.post(path, json=...) -> resp` where
`resp` has `.status_code` and `.json()`. Production passes an `httpx.Client` pointed at this same
API; tests pass a FastAPI `TestClient` bound to an in-memory DB (both exercise the real route).
"""
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.case import RevenueRiskCase
from app.schemas.events import EventPayload
from app.schemas.enums import EventType, PaymentStatus
from app.observability import traceable


def _scan_uncased_failed_payments(db: Session) -> List[Dict[str, Any]]:
    """FAILED payments with no existing case, materialized into plain dicts.

    Returning plain dicts (not live ORM rows) matters: we release the read transaction before the
    POST loop, and each nested `/events/` write runs in its own transaction.
    """
    cased = db.query(RevenueRiskCase.payment_id).filter(RevenueRiskCase.payment_id.isnot(None))
    pending = (
        db.query(Payment)
        .filter(Payment.status == PaymentStatus.FAILED.value)
        .filter(~Payment.id.in_(cased))
        .order_by(Payment.id)
        .all()
    )
    return [
        {
            "payment_id": p.id,
            "customer_id": p.customer_id,
            "amount": p.amount,
            "currency": p.currency,
        }
        for p in pending
    ]


@traceable(name="service.detector.emit_failed_payment_events", run_type="chain")
def emit_failed_payment_events(
    db: Session, client, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Detect uncased failed payments and emit a `PAYMENT_FAILED` event for each over HTTP.

    Idempotent: payments that already have a case are skipped at scan time, and the `/events/`
    handler itself dedupes by payment_id, so re-running creates no duplicate cases.
    """
    items = _scan_uncased_failed_payments(db)

    # Release SQLite's SHARED read lock before the POST loop so the nested /events/ writes (on a
    # separate connection in production) never hit "database is locked". No-op on in-memory test DBs.
    db.rollback()

    results: List[Dict[str, Any]] = []
    cases_created = 0
    already_cased = 0
    errors = 0

    for item in items:
        payload = EventPayload(
            event_type=EventType.PAYMENT_FAILED,
            customer_id=item["customer_id"],
            payment_id=item["payment_id"],
            amount=item["amount"],
            currency=item["currency"],
        ).model_dump(mode="json")

        post_kwargs: Dict[str, Any] = {"json": payload}
        if headers:
            post_kwargs["headers"] = headers

        resp = client.post("/events/", **post_kwargs)  # trailing slash avoids a 307 redirect

        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}

        status = body.get("status") if isinstance(body, dict) else None
        if resp.status_code == 200 and status == "success":
            cases_created += 1
        elif resp.status_code == 200 and status == "exists":
            already_cased += 1
        else:
            errors += 1

        results.append(
            {"payment_id": item["payment_id"], "status_code": resp.status_code, "body": body}
        )

    return {
        "scanned": len(items),
        "cases_created": cases_created,
        "already_cased": already_cased,
        "errors": errors,
        "results": results,
    }
