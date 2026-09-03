"""AI decision output contracts (PRD §31, §56).

The LLM must *always* return structured output validated against these Pydantic schemas before the
system will act on it. The deterministic fallbacks in the diagnose/plan nodes construct the very
same shapes, so everything downstream (EV scoring, policy, tools) is agnostic to whether a real
model or the heuristic produced the values.

Crucially, the ``expected_recovery_probability`` / ``estimated_cost`` the LLM proposes here are
*hints* only — the deterministic ``score_ev`` node recomputes probability from the payment
simulator and cost from the fixed cost table before any money-moving decision (principle §12/§47).
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Diagnosis(BaseModel):
    """§14 — what happened, why, how confident, and the supporting evidence."""

    type: str = Field(description="Snake-case root cause, e.g. 'gateway_degradation'.")
    confidence: float = Field(ge=0.0, le=1.0, description="Calibrated confidence in the diagnosis.")
    evidence: List[str] = Field(default_factory=list, description="Concrete signals supporting it.")
    promise_to_pay_date: Optional[str] = Field(default=None, description="ISO8601 date extracted from communications, if customer promised to pay.")


class CandidateAction(BaseModel):
    """§15 — one proposed intervention with the model's (untrusted) estimates."""

    action: str = Field(description="An InterventionType value, e.g. 'SWITCH_GATEWAY'.")
    expected_recovery_probability: float = Field(ge=0.0, le=1.0)
    estimated_cost: float = Field(ge=0.0)
    discount_amount: Optional[float] = Field(default=None, description="Amount to discount if offering a discount (e.g. SEND_DISCOUNT_MESSAGE).")
    rationale: str = ""


class RecoveryPlan(BaseModel):
    """§15/§31 — the planner's candidate set plus a short natural-language justification."""

    candidate_actions: List[CandidateAction] = Field(default_factory=list)
    reasoning_summary: str = ""
