import random
from typing import Dict, Any
from sqlalchemy.orm import Session

from app.models.checkout import Checkout
from app.models.customer import Customer
from app.schemas.enums import InterventionType
from app.observability import traceable


class CheckoutNotFoundError(LookupError):
    pass


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


@traceable(name="sim.simulate_checkout", run_type="tool")
def simulate_checkout_action(db: Session, checkout_id: str, action: str, attempt: int = 1) -> Dict[str, Any]:
    checkout = db.query(Checkout).filter(Checkout.id == checkout_id).first()
    if checkout is None:
        raise CheckoutNotFoundError(checkout_id)

    customer = db.query(Customer).filter(Customer.id == checkout.customer_id).first()
    intent = customer.intent_score if customer and customer.intent_score is not None else 0.0

    # Discount has a higher baseline probability than a plain reminder
    if action == InterventionType.SEND_DISCOUNT_MESSAGE.value:
        p = clamp01(intent + 0.3)
    elif action == InterventionType.SEND_REMINDER.value:
        p = clamp01(intent)
    else:
        p = 0.0

    # Deterministic roll based on checkout id
    rng = random.Random(f"{checkout_id}_{action}_{attempt}")
    roll = rng.random()
    success = roll < p

    return {
        "checkout_id": checkout.id,
        "action": action,
        "attempt": attempt,
        "success": success,
        "probability": round(p, 4),
        "recovery_roll": round(roll, 4),
        "signals": {
            "customer_intent": round(intent, 4),
        },
    }
