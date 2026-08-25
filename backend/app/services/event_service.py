import uuid
from typing import Optional
from sqlalchemy.orm import Session
from app.schemas.events import EventPayload
from app.schemas.enums import EventType, CaseType, CaseStatus, InterventionType
from app.models.case import RevenueRiskCase
from app.models.audit import AuditEvent
from app.models.payment import Payment
from app.models.customer import Customer
from app.simulation import payment_sim  # read-only §28 oracle (no DB mutation)
from app.observability import traceable
from app.domain.ids import generate_id


@traceable(name="service.event.initial_recovery_probability", run_type="tool")
def _initial_recovery_probability(
    db: Session, payment: Optional[Payment], customer: Optional[Customer]
) -> Optional[float]:
    """Best-of retry/switch/link recovery probability at detection time (PRD §28).

    Reuses the deterministic oracle in `payment_sim`. Returns None when we lack the payment or
    customer needed to compute it (the case still gets created, just without an estimate).
    """
    if payment is None or customer is None:
        return None

    rates = payment_sim.load_gateway_rates(db)
    intent = customer.intent_score if customer.intent_score is not None else 0.0
    method_health = payment.method_health if payment.method_health is not None else 1.0

    best = 0.0
    for action in (
        InterventionType.RETRY_PAYMENT.value,
        InterventionType.SWITCH_GATEWAY.value,
        InterventionType.CREATE_PAYMENT_LINK.value,
    ):
        gw_health, _ = payment_sim.gateway_health_for(rates, payment.gateway, action)
        # A payment link lets the customer re-enter a healthy instrument, so method health resets.
        mh = 1.0 if action == InterventionType.CREATE_PAYMENT_LINK.value else method_health
        best = max(best, payment_sim.recovery_probability(intent, gw_health, mh))
    return round(best, 4)


@traceable(name="service.event.handle_event", run_type="chain")
def handle_event(db: Session, event: EventPayload):
    # Base response
    response = {"status": "ignored", "reason": "Event type not handled"}

    if event.event_type == EventType.PAYMENT_FAILED:
        if not event.payment_id or not event.customer_id:
            raise ValueError("PAYMENT_FAILED event requires payment_id and customer_id")

        # Idempotency (§38): one case per failed payment. A repeat event returns the existing case
        # instead of creating a duplicate -- this is what makes re-running detection safe.
        existing = (
            db.query(RevenueRiskCase)
            .filter(RevenueRiskCase.payment_id == event.payment_id)
            .first()
        )
        if existing is not None:
            return {"status": "exists", "case_id": existing.id}

        # Fetch payment and customer to calculate risk, priority, and recovery probability
        payment = db.query(Payment).filter(Payment.id == event.payment_id).first()
        customer = db.query(Customer).filter(Customer.id == event.customer_id).first()

        amount_at_risk = event.amount
        if payment:
            amount_at_risk = payment.amount

        risk_score = 0.5  # default
        priority = "MEDIUM"
        if customer:
            risk_score = min(1.0, customer.risk_score + 0.1)  # Bump risk score for failed payment
            if customer.ltv_amount > 5000:
                priority = "HIGH"

        recovery_probability = _initial_recovery_probability(db, payment, customer)

        # Create Case
        case = RevenueRiskCase(
            id=generate_id("RR", db),
            customer_id=event.customer_id,
            payment_id=event.payment_id,
            case_type=CaseType.FAILED_PAYMENT.value,
            status=CaseStatus.DETECTED.value,
            amount_at_risk=amount_at_risk,
            priority=priority,
            risk_score=risk_score,
            recovery_probability=recovery_probability,
        )
        db.add(case)
        db.commit()

        # Create Audit Event
        audit = AuditEvent(
            id=generate_id("AUD", db),
            case_id=case.id,
            event_type="CASE_CREATED",
            actor="SYSTEM",
            payload_json={
                "trigger_event": event.event_type.value,
                "payment_id": event.payment_id,
                "initial_risk_score": risk_score,
                "initial_recovery_probability": recovery_probability,
            },
        )
        db.add(audit)
        db.commit()

        response = {
            "status": "success",
            "case_id": case.id,
            "audit_id": audit.id,
        }

    return response
