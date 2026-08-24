"""Deterministic payment-simulation engine (PRD §28).

The recovery probability of an action is:

    p = customer_intent x gateway_health x method_health

Each payment carries a fixed `recovery_roll` in [0, 1) drawn once at generation time. An action
"succeeds" iff `recovery_roll < p`. Because the roll is stored, the outcome is a pure deterministic
function of (payment, action) -> it is reproducible and idempotent (§38): calling twice yields the
same result, and re-running the seeded simulator reproduces every outcome.

This module is the single source of truth for the recovery math. The generator calls the pure
helpers to project ground-truth recoverability; the API/agent tools call `simulate_payment` against
persisted rows. It performs NO writes -- it is a read-only oracle. Phase 4 tools will wrap it with
persistence, audit, and idempotency-key handling.
"""
from typing import Dict, Tuple
from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.customer import Customer
from app.models.metric import GatewayMetric
from app.schemas.enums import InterventionType
from app.observability import traceable


class PaymentNotFoundError(LookupError):
    """Raised by simulate_payment when the payment id does not exist."""


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def recovery_probability(customer_intent: float, gateway_health: float, method_health: float) -> float:
    """The §28 formula, clamped to [0, 1]."""
    return clamp01(customer_intent * gateway_health * method_health)


def gateway_health_for(
    gateway_rates: Dict[str, float], current_gateway: str, action: str
) -> Tuple[float, str]:
    """Resolve which gateway (and its success rate) an action would run through.

    - SWITCH_GATEWAY   -> the healthiest *alternative* gateway.
    - CREATE_PAYMENT_LINK -> the healthiest gateway overall.
    - RETRY_PAYMENT (default) -> the payment's current gateway.
    """
    if action == InterventionType.SWITCH_GATEWAY.value:
        alternatives = {g: r for g, r in gateway_rates.items() if g != current_gateway}
        if alternatives:
            best = max(alternatives, key=alternatives.get)
            return alternatives[best], best
        return gateway_rates.get(current_gateway, 0.0), current_gateway

    if action == InterventionType.CREATE_PAYMENT_LINK.value:
        if gateway_rates:
            best = max(gateway_rates, key=gateway_rates.get)
            return gateway_rates[best], best
        return 0.0, current_gateway

    # RETRY_PAYMENT and any other same-gateway action
    return gateway_rates.get(current_gateway, 0.0), current_gateway


def load_gateway_rates(db: Session) -> Dict[str, float]:
    """Latest success_rate per gateway (most recent metric wins if a gateway has several)."""
    rates: Dict[str, float] = {}
    for m in db.query(GatewayMetric).order_by(GatewayMetric.recorded_at).all():
        rates[m.gateway_name] = m.success_rate
    return rates


@traceable(name="sim.simulate_payment", run_type="tool")
def simulate_payment(db: Session, payment_id: str, action: str, attempt: int = 1) -> dict:
    """Deterministically resolve the outcome of `action` on a persisted payment.

    Read-only. `attempt` is echoed for the caller's idempotency bookkeeping but does not change the
    outcome in this phase (the stored roll fully determines it).
    """
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment is None:
        raise PaymentNotFoundError(payment_id)

    customer = db.query(Customer).filter(Customer.id == payment.customer_id).first()
    customer_intent = customer.intent_score if customer and customer.intent_score is not None else 0.0

    # A payment link lets the customer re-enter a healthy instrument, so method health is reset.
    if action == InterventionType.CREATE_PAYMENT_LINK.value:
        method_health = 1.0
    else:
        method_health = payment.method_health if payment.method_health is not None else 1.0

    gateway_rates = load_gateway_rates(db)
    gateway_health, gateway_used = gateway_health_for(gateway_rates, payment.gateway, action)

    p = recovery_probability(customer_intent, gateway_health, method_health)
    # Fail-safe: missing roll must never manufacture a recovery.
    roll = payment.recovery_roll if payment.recovery_roll is not None else 1.0
    success = roll < p

    return {
        "payment_id": payment.id,
        "action": action,
        "attempt": attempt,
        "success": success,
        "probability": round(p, 4),
        "gateway_used": gateway_used,
        "recovery_roll": round(roll, 4),
        "signals": {
            "customer_intent": round(customer_intent, 4),
            "gateway_health": round(gateway_health, 4),
            "method_health": round(method_health, 4),
        },
    }
