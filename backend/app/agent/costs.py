"""Deterministic intervention cost table (PRD §15, §23, §47).

Every intervention has an economic cost, and the agent optimizes *expected net recovery*
(``amount_at_risk × p − cost``), never raw recovery rate (§47). These costs are business policy —
so they live in deterministic code, never in an LLM's head (principle §12). Values are illustrative
INR figures drawn from the PRD's own examples (§15 uses ₹20 for a gateway switch).
"""
from __future__ import annotations

from app.schemas.enums import InterventionType

# Cost in INR to *attempt* each intervention (charged whether or not it recovers the money).
INTERVENTION_COSTS: dict[str, float] = {
    InterventionType.RETRY_PAYMENT.value: 0.0,       # a bare retry on the same rail is free
    InterventionType.SWITCH_GATEWAY.value: 20.0,     # PRD §15 example
    InterventionType.CREATE_PAYMENT_LINK.value: 5.0,  # generate + deliver a hosted link
    InterventionType.SEND_REMINDER.value: 8.0,
    InterventionType.SEND_DISCOUNT_MESSAGE.value: 10.0,
    InterventionType.OFFER_PAYMENT_PLAN.value: 12.0,
    InterventionType.ESCALATE_TO_HUMAN.value: 0.0,   # cost of human time is tracked separately
    InterventionType.NO_ACTION.value: 0.0,
}


def cost_of(action: str) -> float:
    """Attempt cost of ``action`` (unknown actions cost 0.0 rather than raising)."""
    return INTERVENTION_COSTS.get(action, 0.0)
