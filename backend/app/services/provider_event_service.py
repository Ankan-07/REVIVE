"""Provider Event service (PRD §38, Phase B1).

Manages:
- Race-safe idempotent persistence of incoming provider webhook events (UNIQUE razorpay_event_id).
- HMAC failure tracking and alerting against suspicious spikes (B1.1, A3.5).
- Webhook business event processing (failed, captured, refunded, disputed, expired).
"""
import logging
import threading
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.audit import recorder
from app.config import settings
from app.domain.ids import generate_id
from app.models.case import RevenueRiskCase
from app.models.customer import Customer
from app.models.outcome import RecoveryOutcome
from app.models.payment import Payment
from app.models.provider_event import ProviderEvent
from app.observability import traceable
from app.schemas.enums import CaseStatus, CaseType, EscalationReason, OutcomeType, PaymentStatus
from app.services import (
    case_service,
    escalation_service,
    intervention_service,
    outcome_service,
    provider_object_service,
)

logger = logging.getLogger("revive.provider_events")

# In-memory sliding-window tracker for HMAC failures (thread-safe)
_hmac_failure_lock = threading.Lock()
_hmac_failure_timestamps: list[float] = []


def record_hmac_failure(
    db: Session,
    *,
    reason: str,
    client_ip: str = "unknown",
) -> int:
    """Record an HMAC signature verification failure, audit it, and alert if threshold is exceeded.

    Maintains a rolling 5-minute window of failure timestamps. If count exceeds
    settings.hmac_failure_alert_threshold, an alert is triggered (B1.1, A3.5).
    """
    now = time.time()
    with _hmac_failure_lock:
        _hmac_failure_timestamps.append(now)
        cutoff = now - 300.0  # 5 minutes
        _hmac_failure_timestamps[:] = [t for t in _hmac_failure_timestamps if t >= cutoff]
        recent_count = len(_hmac_failure_timestamps)

    recorder.record(
        db,
        case_id=None,
        event_type="WEBHOOK_SIGNATURE_FAILED",
        payload={
            "reason": reason,
            "client_ip": client_ip,
            "recent_failures_5m": recent_count,
            "threshold": settings.hmac_failure_alert_threshold,
        },
        actor="SYSTEM",
    )

    if recent_count >= settings.hmac_failure_alert_threshold:
        logger.critical(
            f"[SECURITY ALERT] Razorpay webhook HMAC failure spike: {recent_count} failures "
            f"within 5 minutes (threshold: {settings.hmac_failure_alert_threshold}). "
            f"Alert recipient: {settings.admin_alert_email or 'unconfigured'}."
        )

    return recent_count


@traceable(name="service.provider_event.record_raw_event", run_type="tool")
def record_raw_event(
    db: Session,
    *,
    provider: str = "razorpay",
    razorpay_event_id: str,
    event_type: str,
    payload_json: Dict[str, Any],
) -> Tuple[str, bool, bool]:
    """Persist a raw webhook event with race-safe deduplication.

    Returns:
        (event_pk_id, is_new, processed)
    """
    event_pk_id = f"PEV-{uuid.uuid4().hex[:16]}"
    event = ProviderEvent(
        id=event_pk_id,
        provider=provider,
        razorpay_event_id=razorpay_event_id,
        event_type=event_type,
        payload_json=payload_json,
        processed=False,
    )
    try:
        db.add(event)
        db.commit()
        return event_pk_id, True, False
    except (IntegrityError, OperationalError):
        db.rollback()
        existing = (
            db.query(ProviderEvent)
            .filter(ProviderEvent.razorpay_event_id == razorpay_event_id)
            .first()
        )
        if existing is not None:
            return str(existing.id), False, bool(existing.processed)
        # Fallback if another error occurred
        raise


def get_event_by_id(db: Session, event_id: str) -> Optional[ProviderEvent]:
    return db.query(ProviderEvent).filter(ProviderEvent.id == event_id).first()


def _get_entity(payload: Dict[str, Any], key: str) -> Dict[str, Any]:
    """Safely extract nested Razorpay entity object."""
    p = payload.get("payload", {})
    if key in p and isinstance(p[key], dict) and "entity" in p[key]:
        return p[key]["entity"]
    if key in payload and isinstance(payload[key], dict) and "entity" in payload[key]:
        return payload[key]["entity"]
    if key in payload and isinstance(payload[key], dict):
        return payload[key]
    return {}


@traceable(name="service.provider_event.process_provider_event", run_type="chain")
def process_provider_event(db: Session, event_id: str) -> Dict[str, Any]:
    """Process a recorded provider webhook event against domain models.

    Handles:
    - payment.failed -> ingest or update case, update provider_objects
    - payment.captured / payment_link.paid -> settle, update ledger, record RECOVERED
    - payment.refunded -> reverse recovery outcome, debit ledger, flag REFUNDED
    - payment.dispute.created -> flag DISPUTED, create escalation row
    - payment_link.expired -> update provider_objects status
    - invoice.expired -> update provider_objects status
    """
    event = get_event_by_id(db, event_id)
    if not event:
        return {"status": "not_found", "event_id": event_id}
    if event.processed:
        return {"status": "already_processed", "event_id": event_id}

    event_type = event.event_type or ""
    payload = event.payload_json or {}

    result: Dict[str, Any] = {"status": "processed", "event_type": event_type, "event_id": event_id}

    # ----------------------------------------------------------------------------------
    # 1. PAYMENT.FAILED
    # ----------------------------------------------------------------------------------
    if event_type == "payment.failed":
        payment_entity = _get_entity(payload, "payment")
        payment_id = payment_entity.get("id")
        order_id = payment_entity.get("order_id")
        amount_paise = payment_entity.get("amount", 0)
        notes = payment_entity.get("notes") or {}
        case_id = notes.get("case_id")

        if payment_id:
            provider_object_service.record_object(
                db,
                case_id=case_id,
                object_type="payment",
                provider_object_id=payment_id,
                amount_paise=amount_paise,
                status="failed",
            )

        case = None
        if case_id:
            case = case_service.get_case_row(db, case_id)
        if not case and order_id:
            pobj = provider_object_service.get_by_provider_id(db, order_id)
            if pobj and pobj.case_id:
                case = case_service.get_case_row(db, pobj.case_id)
        if not case and payment_id:
            case = db.query(RevenueRiskCase).filter(RevenueRiskCase.payment_id == payment_id).first()

        if not case:
            # Organic live payment failure -> Ingest a new LIVE case (origin="live")
            customer_email = payment_entity.get("email") or "live_customer@example.com"
            customer_contact = payment_entity.get("contact") or "+919999999999"
            cust = db.query(Customer).filter(Customer.email == customer_email).first()
            if not cust:
                cust = Customer(
                    id=generate_id("CUS", db),
                    name=notes.get("customer_name") or "Live Customer",
                    email=customer_email,
                    phone=customer_contact,
                    origin="live",
                    risk_score=0.5,
                )
                db.add(cust)
                db.flush()

            pay_row = db.query(Payment).filter(Payment.id == payment_id).first() if payment_id else None
            if not pay_row:
                pay_row = Payment(
                    id=payment_id or generate_id("PAY", db),
                    customer_id=cust.id,
                    amount=float(amount_paise) / 100.0 if amount_paise else 0.0,
                    currency=payment_entity.get("currency", "INR"),
                    status=PaymentStatus.FAILED.value,
                    gateway="RAZORPAY",
                    origin="live",
                    error_code=payment_entity.get("error_code"),
                    error_message=payment_entity.get("error_description"),
                )
                db.add(pay_row)
                db.flush()

            case = RevenueRiskCase(
                id=generate_id("RR", db),
                customer_id=cust.id,
                payment_id=pay_row.id,
                case_type=CaseType.FAILED_PAYMENT.value,
                origin="live",
                status=CaseStatus.DETECTED.value,
                amount_at_risk=pay_row.amount,
                priority="HIGH" if pay_row.amount and pay_row.amount > 5000 else "MEDIUM",
                risk_score=0.6,
            )
            db.add(case)
            db.flush()

            recorder.record(
                db,
                case.id,
                "PAYMENT_FAILED_INGESTED",
                payload={"payment_id": pay_row.id, "amount": pay_row.amount, "provider": "razorpay"},
                actor="SYSTEM",
            )
        result["case_id"] = case.id if case else None

    # ----------------------------------------------------------------------------------
    # 2. PAYMENT.CAPTURED / PAYMENT_LINK.PAID
    # ----------------------------------------------------------------------------------
    elif event_type in ("payment.captured", "payment_link.paid"):
        payment_entity = _get_entity(payload, "payment")
        link_entity = _get_entity(payload, "payment_link")
        payment_id = payment_entity.get("id")
        order_id = payment_entity.get("order_id")
        link_id = link_entity.get("id")
        amount_paise = payment_entity.get("amount") or link_entity.get("amount") or 0
        fee_paise = payment_entity.get("fee", 0)

        case = None
        target_obj_id = link_id or order_id or payment_id
        if target_obj_id:
            pobj = provider_object_service.get_by_provider_id(db, target_obj_id)
            if pobj and pobj.case_id:
                case = case_service.get_case_row(db, pobj.case_id)
        if not case and payment_id:
            case = db.query(RevenueRiskCase).filter(RevenueRiskCase.payment_id == payment_id).first()

        if order_id:
            provider_object_service.update_status(db, provider_object_id=order_id, status="paid")
        if link_id:
            provider_object_service.update_status(db, provider_object_id=link_id, status="paid")
        if payment_id:
            provider_object_service.record_object(
                db,
                case_id=case.id if case else None,
                object_type="payment",
                provider_object_id=payment_id,
                amount_paise=amount_paise,
                fee_paise=fee_paise,
                status="captured",
            )

        if case:
            gross = float(amount_paise) / 100.0 if amount_paise else float(case.amount_at_risk or 0.0)
            totals = intervention_service.totals(db, case.id)
            cost_total = totals["cost_total"]
            discount_total = totals["discount_total"]

            outcome_type = (
                OutcomeType.RECOVERED_PARTIAL.value
                if case.amount_at_risk and 0 < gross < float(case.amount_at_risk)
                else OutcomeType.RECOVERED_FULL.value
            )

            outcome = outcome_service.record_outcome(
                db,
                case_id=case.id,
                outcome_type=outcome_type,
                gross_recovered=gross,
                cost_total=cost_total,
                discount_total=discount_total,
                gateway_fee_paise=fee_paise or 0,
                verified=True,
            )
            case_service.set_net_recovered(db, case.id, outcome.net_recovered)
            case_service.set_status(db, case.id, CaseStatus.RECOVERED.value)
            case_service.set_current_action(db, case.id, None)

            if case.payment_id:
                pay = db.query(Payment).filter(Payment.id == case.payment_id).first()
                if pay:
                    pay.status = PaymentStatus.SUCCEEDED.value

            recorder.record(
                db,
                case.id,
                "RECOVERED",
                payload={
                    "outcome_type": outcome_type,
                    "gross_recovered": gross,
                    "net_recovered": outcome.net_recovered,
                    "gateway_fee": float(fee_paise or 0) / 100.0,
                    "fee_paise": fee_paise,
                    "verified_via": "razorpay_webhook",
                    "razorpay_payment_id": payment_id,
                },
                actor="SYSTEM",
            )
        result["case_id"] = case.id if case else None

    # ----------------------------------------------------------------------------------
    # 3. PAYMENT.REFUNDED
    # ----------------------------------------------------------------------------------
    elif event_type == "payment.refunded":
        refund_entity = _get_entity(payload, "refund")
        payment_entity = _get_entity(payload, "payment")
        payment_id = refund_entity.get("payment_id") or payment_entity.get("id")
        refund_id = refund_entity.get("id")
        refund_amount_paise = refund_entity.get("amount") or payment_entity.get("amount_refunded") or 0
        refund_amount = float(refund_amount_paise) / 100.0 if refund_amount_paise else 0.0

        case = None
        if payment_id:
            pobj = provider_object_service.get_by_provider_id(db, payment_id)
            if pobj and pobj.case_id:
                case = case_service.get_case_row(db, pobj.case_id)
            if not case:
                case = db.query(RevenueRiskCase).filter(RevenueRiskCase.payment_id == payment_id).first()

        if case:
            # 1. Reverse recovery outcome
            latest_outcome = (
                db.query(RecoveryOutcome)
                .filter(RecoveryOutcome.case_id == case.id)
                .order_by(RecoveryOutcome.created_at.desc(), RecoveryOutcome.id.desc())
                .first()
            )
            if latest_outcome:
                latest_outcome.outcome_type = OutcomeType.REFUNDED.value
                latest_outcome.net_recovered = max(0.0, float(latest_outcome.net_recovered or 0.0) - refund_amount)
                db.flush()

            # 2. Update case status & debit net recovered amount
            case_service.set_status(db, case.id, CaseStatus.REFUNDED.value)
            case_service.set_net_recovered(db, case.id, 0.0)

            # 3. Update payment status if exists
            if case.payment_id:
                pay = db.query(Payment).filter(Payment.id == case.payment_id).first()
                if pay:
                    pay.status = "REFUNDED"

            # 4. Record audit event
            recorder.record(
                db,
                case.id,
                "PAYMENT_REFUNDED",
                payload={
                    "refund_id": refund_id,
                    "payment_id": payment_id,
                    "amount_refunded": refund_amount,
                    "outcome_reversed": True,
                },
                actor="SYSTEM",
            )

        if payment_id:
            provider_object_service.update_status(db, provider_object_id=payment_id, status="refunded")

        result["case_id"] = case.id if case else None

    # ----------------------------------------------------------------------------------
    # 4. PAYMENT.DISPUTE.CREATED
    # ----------------------------------------------------------------------------------
    elif event_type == "payment.dispute.created":
        dispute_entity = _get_entity(payload, "dispute")
        payment_entity = _get_entity(payload, "payment")
        payment_id = dispute_entity.get("payment_id") or payment_entity.get("id")
        dispute_id = dispute_entity.get("id")
        dispute_reason = dispute_entity.get("reason_code") or "DISPUTE_FILED"

        case = None
        if payment_id:
            pobj = provider_object_service.get_by_provider_id(db, payment_id)
            if pobj and pobj.case_id:
                case = case_service.get_case_row(db, pobj.case_id)
            if not case:
                case = db.query(RevenueRiskCase).filter(RevenueRiskCase.payment_id == payment_id).first()

        if case:
            case_service.set_status(db, case.id, CaseStatus.DISPUTED.value)
            escalation = escalation_service.create_escalation(
                db,
                case_id=case.id,
                reason=EscalationReason.DISPUTE_FILED.value,
                priority="HIGH",
                notes=f"Razorpay dispute {dispute_id} created for payment {payment_id}. Reason: {dispute_reason}",
            )
            recorder.record(
                db,
                case.id,
                "PAYMENT_DISPUTED",
                payload={
                    "dispute_id": dispute_id,
                    "payment_id": payment_id,
                    "escalation_id": escalation.id,
                    "reason": dispute_reason,
                },
                actor="SYSTEM",
            )
        result["case_id"] = case.id if case else None

    # ----------------------------------------------------------------------------------
    # 5. PAYMENT_LINK.EXPIRED
    # ----------------------------------------------------------------------------------
    elif event_type == "payment_link.expired":
        link_entity = _get_entity(payload, "payment_link")
        link_id = link_entity.get("id")
        case = None
        if link_id:
            provider_object_service.update_status(db, provider_object_id=link_id, status="expired")
            pobj = provider_object_service.get_by_provider_id(db, link_id)
            if pobj and pobj.case_id:
                case = case_service.get_case_row(db, pobj.case_id)

        recorder.record(
            db,
            case.id if case else None,
            "PAYMENT_LINK_EXPIRED",
            payload={"payment_link_id": link_id},
            actor="SYSTEM",
        )
        result["case_id"] = case.id if case else None

    # ----------------------------------------------------------------------------------
    # 6. INVOICE.EXPIRED
    # ----------------------------------------------------------------------------------
    elif event_type == "invoice.expired":
        inv_entity = _get_entity(payload, "invoice")
        inv_id = inv_entity.get("id")
        case = None
        if inv_id:
            provider_object_service.update_status(db, provider_object_id=inv_id, status="expired")
            pobj = provider_object_service.get_by_provider_id(db, inv_id)
            if pobj and pobj.case_id:
                case = case_service.get_case_row(db, pobj.case_id)

        recorder.record(
            db,
            case.id if case else None,
            "INVOICE_EXPIRED",
            payload={"invoice_id": inv_id},
            actor="SYSTEM",
        )
        result["case_id"] = case.id if case else None

    event.processed = True
    db.commit()
    db.refresh(event)
    return result
