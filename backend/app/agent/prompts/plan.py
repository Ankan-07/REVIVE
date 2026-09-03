"""Plan-node prompts (PRD §15, §32).

The planner proposes a *candidate set* of recovery actions given the diagnosis and the actions the
simulator says are available (with their oracle-estimated recovery probabilities and fixed costs).
It returns JSON matching :class:`app.agent.contracts.RecoveryPlan`.

Critically, the model's probability/cost numbers are **hints only** — the deterministic ``score_ev``
node recomputes both from the payment simulator and the cost table before any decision (principle
§12/§47). The prompt says so explicitly, to discourage the model from anchoring on invented figures.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

PLAN_SYSTEM = (
    "You are the planning stage of an autonomous revenue-recovery agent. Given a diagnosis and a set "
    "of ALLOWED recovery actions (each with a simulator-estimated recovery probability and a fixed "
    "cost), propose a ranked set of candidate actions to attempt.\n"
    "Rules:\n"
    "1. Choose ONLY from the allowed actions listed; never invent an action.\n"
    "2. Your probability and cost fields are hints — the system will INDEPENDENTLY recompute the "
    "real probability from its payment simulator and the real cost from its cost table, then pick "
    "the action with the highest expected NET recovery. Do not try to game these numbers.\n"
    "3. Prefer actions that plausibly address the diagnosed root cause.\n"
    "4. If offering a discount (e.g. SEND_DISCOUNT_MESSAGE), specify the proposed discount amount in `discount_amount`.\n"
    "5. Keep rationales short and factual.\n"
    "Respond with ONLY a JSON object of the form "
    '{"candidate_actions": [{"action": <ALLOWED_ACTION>, '
    '"expected_recovery_probability": <float 0..1>, "estimated_cost": <float>=0>, "discount_amount": <optional float>, '
    '"rationale": <string>}], "reasoning_summary": <string>}.'
)


def build_plan_user(
    diagnosis: Dict[str, Any],
    allowed_actions: List[Dict[str, Any]],
    context: Dict[str, Any],
) -> str:
    """Render the diagnosis + allowed-action menu into the planner's user turn.

    ``allowed_actions`` is a list of ``{action, simulator_probability, cost}`` dicts computed
    deterministically upstream so the model sees the same ground truth the EV scorer will use.
    """
    payload = {
        "diagnosis": diagnosis,
        "amount_at_risk": context.get("amount_at_risk"),
        "allowed_actions": allowed_actions,
    }
    return (
        "Given this diagnosis and the allowed actions with their simulator estimates, propose the "
        "candidate recovery actions to try, best first:\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Return only the JSON plan object."
    )
