"""Deterministic intervention cost table (PRD §15, §23, §47).

Every intervention has an economic cost, and the agent optimizes *expected net recovery*
(``amount_at_risk × p − cost``), never raw recovery rate (§47). These costs are business policy —
so they live in deterministic code, never in an LLM's head (principle §12). Values are illustrative
INR figures drawn from the PRD's own examples (§15 uses ₹20 for a gateway switch).
"""
from __future__ import annotations

from app.schemas.enums import InterventionType

# Cost in INR to *attempt* each intervention (charged whether or not it recovers the money).
# Documented Phase B5 fee schedule & EV scorer table (Source: PRD §15 & Razorpay Test Mode Schedule, 2026-09):
INTERVENTION_COSTS: dict[str, float] = {
    # Bare retry / order creation on Razorpay carries no upfront platform creation fee (Source: Razorpay Orders API, 2026-09)
    InterventionType.RETRY_PAYMENT.value: 0.0,
    # Simulated gateway switching illustrative cost (Source: PRD §15 example, 2026-09)
    InterventionType.SWITCH_GATEWAY.value: 20.0,
    # Hosted payment link generation & delivery (Source: PRD §15 / Razorpay Payment Links API, 2026-09)
    InterventionType.CREATE_PAYMENT_LINK.value: 5.0,
    # Modeled customer messaging outreach (Source: PRD §15 / Comms Schedule, 2026-09)
    InterventionType.SEND_REMINDER.value: 8.0,
    # Modeled discount outreach message (Source: PRD §15 / Comms Schedule, 2026-09)
    InterventionType.SEND_DISCOUNT_MESSAGE.value: 10.0,
    # Modeled payment plan outreach (Source: PRD §15 / Comms Schedule, 2026-09)
    InterventionType.OFFER_PAYMENT_PLAN.value: 12.0,
    # Internal promise verification check (Source: PRD §15, 2026-09)
    InterventionType.VERIFY_PROMISE.value: 2.0,
    # Human staff time tracked separately in operations ledger (Source: PRD §15, 2026-09)
    InterventionType.ESCALATE_TO_HUMAN.value: 0.0,
    InterventionType.NO_ACTION.value: 0.0,
}


def cost_of(action: str) -> float:
    """Attempt cost of ``action`` (unknown actions cost 0.0 rather than raising)."""
    return INTERVENTION_COSTS.get(action, 0.0)
