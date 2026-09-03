"""Per-case-type intervention menu (PRD §15, §47).

The planner (``plan`` node) proposes candidates from this menu and the deterministic EV scorer
(``score_ev`` node) recomputes expected net from the *same* menu, so the two nodes can never drift
apart on which interventions are allowed for a case or what the simulator estimates they are worth.
Adding a new leak type now means registering it here (and in the tools/context dispatchers) once,
instead of re-hard-coding the mapping in every graph node.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.agent.costs import cost_of
from app.schemas.enums import CaseType, InterventionType
from app.simulation import checkout_sim, invoice_sim, payment_sim


def allowed_menu(
    db: Session, case_row, context: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """The allowed actions for a case, with simulator-estimated probability and fixed cost.

    Each entry is ``{"action", "simulator_probability", "cost", "gateway_used"}``.  When the case's
    entity is missing from the context:

    * failed-payment cases contribute **no** menu (nothing can be attempted on an unknown payment);
    * abandoned-checkout / overdue-invoice cases still list their actions at zero probability, so EV
      scoring converges and any attempt fails cleanly in the tool layer (``*_NOT_FOUND``).
    """
    case_type = case_row.case_type
    entity_id: Optional[str]
    if case_type == CaseType.FAILED_PAYMENT.value:
        entity_id = context.get("payment_id")
        actions = [
            (InterventionType.RETRY_PAYMENT.value, payment_sim.simulate_payment),
            (InterventionType.SWITCH_GATEWAY.value, payment_sim.simulate_payment),
            (InterventionType.CREATE_PAYMENT_LINK.value, payment_sim.simulate_payment),
        ]
    elif case_type == CaseType.ABANDONED_CHECKOUT.value:
        entity_id = context.get("checkout_id")
        actions = [
            (InterventionType.SEND_DISCOUNT_MESSAGE.value, checkout_sim.simulate_checkout_action),
            (InterventionType.SEND_REMINDER.value, checkout_sim.simulate_checkout_action),
        ]
    elif case_type == CaseType.OVERDUE_INVOICE.value:
        entity_id = context.get("invoice_id")
        actions = [
            (InterventionType.SEND_REMINDER.value, invoice_sim.simulate_invoice_action),
            (InterventionType.VERIFY_PROMISE.value, invoice_sim.simulate_invoice_action),
        ]
    else:
        return []

    menu: List[Dict[str, Any]] = []
    for action, simulate in actions:
        if entity_id is None:
            if case_type == CaseType.FAILED_PAYMENT.value:
                continue
            probability = 0.0
            gateway_used = None
        else:
            try:
                sim = simulate(db, entity_id, action)
                probability = float(sim["probability"])
                gateway_used = sim.get("gateway_used")
            except Exception:
                # Payment sims raise loudly on a vanished row; the other oracles are best-effort and
                # degrade to a zero-probability entry so the loop still converges.
                if case_type == CaseType.FAILED_PAYMENT.value:
                    raise
                probability = 0.0
                gateway_used = None

        menu.append(
            {
                "action": action,
                "simulator_probability": probability,
                "cost": cost_of(action),
                "gateway_used": gateway_used,
            }
        )
    return menu
