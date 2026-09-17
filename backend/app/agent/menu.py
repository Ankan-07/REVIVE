"""Per-case-type intervention menu (PRD §15, §47).

The planner (``plan`` node) proposes candidates from this menu and the deterministic EV scorer
(``score_ev`` node) recomputes expected net from the *same* menu, so the two nodes can never drift
apart on which interventions are allowed for a case or what the simulator estimates they are worth.

Eval Quarantine (Phase E2):
Zero imports from app.simulation on the live path. Live actions compute probabilities from
gateway metric service; lab benchmarks access registered simulation oracles.
"""
from __future__ import annotations

import importlib
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.agent.costs import cost_of
from app.schemas.enums import CaseType, InterventionType
from app.services.gateway_metric_service import load_gateway_rates

_SIMULATION_ORACLES: Dict[str, Callable] = {}


def register_simulation_oracle(action: str, fn: Callable) -> None:
    """Hook allowing lab simulation to register deterministic oracles for eval runs (Phase E2)."""
    _SIMULATION_ORACLES[action] = fn


def _ensure_lab_oracles_registered() -> None:
    """Lazily load simulation package only when executing lab/eval benchmarks."""
    if not _SIMULATION_ORACLES:
        try:
            importlib.import_module("app.simulation")
        except Exception:
            pass


def allowed_menu(
    db: Session, case_row, context: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """The allowed actions for a case, with simulator-estimated probability and fixed cost.

    Each entry is ``{"action", "simulator_probability", "cost", "gateway_used"}``. When the case's
    entity is missing from the context:

    * failed-payment cases contribute **no** menu (nothing can be attempted on an unknown payment);
    * abandoned-checkout / overdue-invoice cases still list their actions at zero probability, so EV
      scoring converges and any attempt fails cleanly in the tool layer (``*_NOT_FOUND``).
    """
    case_type = case_row.case_type
    origin = getattr(case_row, "origin", "lab") or "lab"
    entity_id: Optional[str]

    if case_type == CaseType.FAILED_PAYMENT.value:
        entity_id = context.get("payment_id")
        if origin == "live":
            # Live track: single provider (Razorpay) -> RETRY_PAYMENT and CREATE_PAYMENT_LINK only (Phase B2)
            actions = [
                InterventionType.RETRY_PAYMENT.value,
                InterventionType.CREATE_PAYMENT_LINK.value,
            ]
        else:
            # Lab track: benchmark evaluation with simulated multi-gateway options
            actions = [
                InterventionType.RETRY_PAYMENT.value,
                InterventionType.SWITCH_GATEWAY.value,
                InterventionType.CREATE_PAYMENT_LINK.value,
            ]
    elif case_type == CaseType.ABANDONED_CHECKOUT.value:
        entity_id = context.get("checkout_id")
        actions = [
            InterventionType.SEND_DISCOUNT_MESSAGE.value,
            InterventionType.SEND_REMINDER.value,
        ]
    elif case_type == CaseType.OVERDUE_INVOICE.value:
        entity_id = context.get("invoice_id")
        actions = [
            InterventionType.SEND_REMINDER.value,
            InterventionType.VERIFY_PROMISE.value,
        ]
    else:
        return []

    menu: List[Dict[str, Any]] = []

    if origin != "live":
        _ensure_lab_oracles_registered()

    for action in actions:
        if entity_id is None:
            if case_type == CaseType.FAILED_PAYMENT.value:
                continue
            probability = 0.0
            gateway_used = None
        else:
            if origin == "live":
                rates = load_gateway_rates(db)
                gateway_used = "RAZORPAY"
                if action == InterventionType.RETRY_PAYMENT.value:
                    probability = rates.get("RAZORPAY", 0.65)
                elif action == InterventionType.CREATE_PAYMENT_LINK.value:
                    probability = 0.50
                else:
                    probability = 0.40
            else:
                sim_fn = _SIMULATION_ORACLES.get(action)
                if sim_fn is not None:
                    try:
                        sim = sim_fn(db, entity_id, action)
                        probability = float(sim["probability"])
                        gateway_used = sim.get("gateway_used")
                    except Exception:
                        if case_type == CaseType.FAILED_PAYMENT.value:
                            raise
                        probability = 0.0
                        gateway_used = None
                else:
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
