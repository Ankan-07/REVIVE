"""score_ev node (PRD §15, §47 — the money math).

The heart of "LLM proposes, deterministic code disposes." For every candidate the planner proposed
that has not already been ruled out, this node recomputes the recovery probability from the
per-case-type simulator menu (see :func:`app.agent.menu.allowed_menu` — never the LLM's number) and
the cost from the fixed cost table, then picks the action with the highest expected NET recovery:

    expected_net = amount_at_risk × p(simulator) − cost(action)

If nothing eligible remains (every candidate rejected by policy or already tried), the node marks the
run terminal as ``CLOSED_NO_RECOVERY`` — this is what makes the retry-exhaustion path converge.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.agent.menu import allowed_menu
from app.agent.nodes.common import RunnableConfig, log_decision, open_session
from app.audit import recorder
from app.observability import traceable
from app.schemas.enums import CaseStatus
from app.services import case_service


@traceable(name="node.score_ev", run_type="chain")
def score_ev(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    case_id = state["case_id"]
    amount = state.get("context", {}).get("amount_at_risk") or 0.0
    rejected = set(state.get("rejected_actions", []))
    candidates = state.get("candidates", [])

    with open_session(config) as db:
        case = case_service.get_case_row(db, case_id)
        if case is None:
            raise LookupError(f"Case {case_id} not found")
        menu = allowed_menu(db, case, state.get("context", {}))
        by_action = {m["action"]: m for m in menu}

        scored: List[Dict[str, Any]] = []
        seen = set()
        for candidate in candidates:
            action = candidate["action"]
            if action in rejected or action in seen:
                continue
            seen.add(action)
            item = by_action.get(action)
            if item is None:
                continue  # the planner only proposes allowed actions; defensive skip
            expected_net = round(amount * item["simulator_probability"] - item["cost"], 4)
            scored.append(
                {
                    "action": action,
                    "probability": item["simulator_probability"],
                    "cost": item["cost"],
                    "expected_net": expected_net,
                    "gateway_used": item.get("gateway_used"),
                }
            )

        if not scored:
            recorder.record(
                db,
                case_id,
                "EV_SCORED",
                payload={"scored": [], "chosen_action": None, "note": "no eligible actions remain"},
            )
            log_decision(
                db,
                case_id=case_id,
                node_name="score_ev",
                output={"chosen_action": None},
                reasoning="all candidate actions rejected or exhausted",
            )
            return {"scored": [], "chosen_action": None, "ev": None, "terminal_status": "CLOSED_NO_RECOVERY"}

        best = max(scored, key=lambda s: s["expected_net"])
        chosen = best["action"]

        case_service.set_status(db, case_id, CaseStatus.SCORE_EV.value)
        case_service.set_current_action(db, case_id, chosen)
        recorder.record(db, case_id, "EV_SCORED", payload={"scored": scored, "chosen_action": chosen})
        log_decision(
            db,
            case_id=case_id,
            node_name="score_ev",
            output={"scored": scored, "chosen_action": chosen, "ev": best},
            reasoning=f"argmax expected_net -> {chosen} (₹{best['expected_net']})",
        )

    return {"scored": scored, "chosen_action": chosen, "ev": best, "terminal_status": None}
