"""Policy Engine (PRD §16, §18; BUILDPLAN Phase 4/5).

The hard control layer. The planner *proposes* an action; :func:`evaluate` decides — purely and
deterministically — whether it is permitted. The LLM can never reach these limits (principle §12,
§56). Rules load from :mod:`policy.yaml` and are cached.

Three outcomes (PRD §16, §22):

* ``APPROVED``  — the action may execute.
* ``REJECTED``  — this action is not allowed; the graph asks the planner/EV scorer for the next best
  permitted action (retry-limit reached, discount over cap, ...).
* ``ESCALATE``  — the case must go to a human and automation halts (e.g. amount over the
  human-approval threshold). A first-class outcome, not a failure.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel

from app.schemas.enums import InterventionType, EscalationReason
from app.observability import traceable

_POLICY_PATH = Path(__file__).resolve().parent / "policy.yaml"

# Payment-recovery attempts all draw down the same retry budget (PRD §16 max_retries).
# These align with Razorpay's native dunning and failed payment recovery actions.
PAYMENT_ATTEMPT_ACTIONS = {
    InterventionType.RETRY_PAYMENT.value,
    InterventionType.SWITCH_GATEWAY.value,
    InterventionType.CREATE_PAYMENT_LINK.value,
}

MESSAGING_ACTIONS = {
    InterventionType.SEND_DISCOUNT_MESSAGE.value,
    InterventionType.SEND_REMINDER.value,
}


class PolicyResult(str):
    """Sentinel-string results (kept simple so they serialize straight into audit JSON)."""


APPROVED = "APPROVED"
REJECTED = "REJECTED"
ESCALATE = "ESCALATE"


class PolicyDecision(BaseModel):
    result: str  # APPROVED | REJECTED | ESCALATE
    reason: Optional[str] = None  # EscalationReason value or a short rejection code
    detail: Optional[str] = None  # human-readable explanation for the audit trail

    @property
    def approved(self) -> bool:
        return self.result == APPROVED


@lru_cache(maxsize=1)
def load_policy() -> Dict[str, Any]:
    """Parse ``policy.yaml`` once and cache it."""
    with _POLICY_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def max_attempts() -> int:
    """Hard cap on graph loops per case (termination guarantee, PRD §21)."""
    return int(load_policy().get("max_attempts", 6))


def outcome_wait_hours() -> int:
    """Bounded wait window (in hours) before an un-captured outcome times out (PRD §37)."""
    return int(load_policy().get("outcome_wait", {}).get("wait_hours", 4))



@traceable(name="policy.evaluate", run_type="tool")
def evaluate(
    action: str,
    *,
    amount_at_risk: float,
    attempt_count: int,
    message_count: int = 0,
    hours_since_creation: float = 0.0,
    hours_since_last_message: Optional[float] = None,
    discount_amount: float = 0.0,
    policy: Optional[Dict[str, Any]] = None,
) -> PolicyDecision:
    """Decide whether ``action`` is permitted for a case in its current state.

    ``attempt_count`` is the number of payment attempts *already executed* on the case.
    Escalation (amount over the human-approval threshold) is checked first because such a case must
    never be auto-actioned at all (PRD §22).
    """
    p = policy or load_policy()

    # 1. Amount gate -> escalate to a human (PRD §22: > ₹1,00,000).
    threshold = float(p.get("human_approval", {}).get("required_above_amount", float("inf")))
    if amount_at_risk > threshold:
        return PolicyDecision(
            result=ESCALATE,
            reason=EscalationReason.AMOUNT_EXCEEDS_POLICY.value,
            detail=f"amount_at_risk {amount_at_risk:.2f} exceeds human-approval threshold {threshold:.2f}",
        )

    # 2. Retry budget and window for payment-recovery attempts (Razorpay Dunning)
    if action in PAYMENT_ATTEMPT_ACTIONS:
        # Check retry window
        retry_window_hours = float(p.get("payment", {}).get("retry_window_hours", 72))
        if hours_since_creation > retry_window_hours:
            return PolicyDecision(
                result=REJECTED,
                reason=EscalationReason.POLICY_REJECTION.value,
                detail=f"case age {hours_since_creation:.1f}h exceeds retry window {retry_window_hours}h",
            )
            
        # Check max retries
        max_retries = int(p.get("payment", {}).get("max_retries", 3))
        if attempt_count >= max_retries:
            return PolicyDecision(
                result=REJECTED,
                reason=EscalationReason.MAX_RETRIES_EXCEEDED.value,
                detail=f"{attempt_count} attempts already used; max_retries={max_retries}",
            )

        # Check minimum amount for payment links
        if action == InterventionType.CREATE_PAYMENT_LINK.value:
            min_amount = float(p.get("payment", {}).get("min_amount", 1))
            if amount_at_risk < min_amount:
                return PolicyDecision(
                    result=REJECTED,
                    reason=EscalationReason.POLICY_REJECTION.value,
                    detail=f"amount_at_risk {amount_at_risk:.2f} is below minimum payment link amount {min_amount:.2f}",
                )

    # 3. Messaging rules (Razorpay Failed Payment Recovery communications)
    if action in MESSAGING_ACTIONS:
        # Check max messages
        max_messages = int(p.get("messaging", {}).get("max_messages_per_case", 3))
        if message_count >= max_messages:
            return PolicyDecision(
                result=REJECTED,
                reason=EscalationReason.POLICY_REJECTION.value,
                detail=f"{message_count} messages already sent; max_messages={max_messages}",
            )
            
        # Check message spacing
        if hours_since_last_message is not None:
            min_spacing = float(p.get("messaging", {}).get("minimum_hours_between_messages", 24))
            if hours_since_last_message < min_spacing:
                return PolicyDecision(
                    result=REJECTED,
                    reason=EscalationReason.POLICY_REJECTION.value,
                    detail=f"only {hours_since_last_message:.1f}h since last message; min spacing is {min_spacing}h",
                )

    # 4. Discount cap (applies to incentive actions; payment slice usually passes 0).
    if discount_amount > 0:
        max_abs = float(p.get("discount", {}).get("max_absolute_amount", 0))
        if discount_amount > max_abs:
            return PolicyDecision(
                result=REJECTED,
                reason=EscalationReason.POLICY_REJECTION.value,
                detail=f"discount {discount_amount:.2f} exceeds max_absolute_amount {max_abs:.2f}",
            )

    return PolicyDecision(result=APPROVED, detail=f"{action} within policy limits")
