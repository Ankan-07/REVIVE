"""policy_check node (PRD §16, §22).

Runs the chosen action past the deterministic policy engine. Three outcomes drive the graph's
conditional edge (see :func:`app.agent.graph.route_after_policy`):

* APPROVED  -> proceed to execute the tool.
* REJECTED  -> add the action to ``rejected_actions`` and loop back to EV scoring for the next best.
* ESCALATE  -> mark the run terminal as ``ESCALATED``; a human must take it (no tool ever runs).
"""
from __future__ import annotations

from typing import Any, Dict

from app.agent.nodes.common import RunnableConfig, log_decision, open_session
from app.audit import recorder
from app.observability import traceable
from app.policies import engine as policy_engine
from app.schemas.enums import CaseStatus
from app.services import case_service


@traceable(name="node.policy_check", run_type="chain")
def policy_check(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    case_id = state["case_id"]
    context = state.get("context", {})
    action = state.get("chosen_action")
    amount = context.get("amount_at_risk") or 0.0

    with open_session(config) as db:
        case = case_service.get_case_row(db, case_id)
        attempt_count = (case.attempt_count or 0) if case else 0

        decision = policy_engine.evaluate(
            action, amount_at_risk=amount, attempt_count=attempt_count
        )
        policy_payload = decision.model_dump()

        case_service.set_status(db, case_id, CaseStatus.POLICY_CHECK.value)
        recorder.record(
            db, case_id, "POLICY_CHECK", payload={"action": action, **policy_payload}
        )
        log_decision(
            db,
            case_id=case_id,
            node_name="policy_check",
            output={"action": action, **policy_payload},
            reasoning=decision.detail or "",
        )

    if decision.result == policy_engine.REJECTED:
        rejected = list(state.get("rejected_actions", []))
        if action not in rejected:
            rejected.append(action)
        return {"policy": policy_payload, "rejected_actions": rejected}

    if decision.result == policy_engine.ESCALATE:
        return {"policy": policy_payload, "terminal_status": "ESCALATED"}

    return {"policy": policy_payload}
