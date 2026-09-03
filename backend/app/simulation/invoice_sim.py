import random
from typing import Dict, Any
from sqlalchemy.orm import Session

from app.models.invoice import Invoice
from app.models.customer import Customer
from app.schemas.enums import InterventionType
from app.observability import traceable


class InvoiceNotFoundError(LookupError):
    pass


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


@traceable(name="sim.simulate_invoice", run_type="tool")
def simulate_invoice_action(db: Session, invoice_id: str, action: str, attempt: int = 1) -> Dict[str, Any]:
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if invoice is None:
        raise InvoiceNotFoundError(invoice_id)

    customer = db.query(Customer).filter(Customer.id == invoice.customer_id).first()
    intent = customer.intent_score if customer and customer.intent_score is not None else 0.0

    if action == InterventionType.SEND_REMINDER.value:
        p = clamp01(intent + 0.1)
    elif action == InterventionType.VERIFY_PROMISE.value:
        # A promise to pay is kept primarily based on customer intent
        p = clamp01(intent + 0.5)
    else:
        p = 0.0

    # Deterministic roll based on invoice id
    rng = random.Random(f"{invoice_id}_{action}_{attempt}")
    roll = rng.random()
    success = roll < p

    return {
        "invoice_id": invoice.id,
        "action": action,
        "attempt": attempt,
        "success": success,
        "probability": round(p, 4),
        "recovery_roll": round(roll, 4),
        "signals": {
            "customer_intent": round(intent, 4),
        },
    }
