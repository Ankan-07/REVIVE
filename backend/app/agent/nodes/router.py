"""router node (PRD §20, §21 — the stopping rule).

Given a verified outcome, decides the next move and guarantees termination:

* recovered            -> finalize as RECOVERED.
* not recovered, budget left -> add the tried action to ``rejected_actions`` and loop to EV scoring
  for the next best permitted action.
* iteration cap reached      -> finalize as CLOSED_NO_RECOVERY.

The iteration counter is a hard backstop independent of the policy retry budget, so the graph can
never loop forever even if some future action type sits outside the retry accounting (principle §7.7).
"""
from __future__ import annotations

from typing import Any, Dict

from app.agent.nodes.common import RunnableConfig, log_decision, open_session
from app.audit import recorder
from app.observability import traceable
from app.policies import engine as policy_engine


@traceable(name="node.router", run_type="chain")
def router(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    case_id = state["case_id"]
    outcome = state.get("outcome") or {}
    iterations = int(state.get("iterations", 0)) + 1
    max_iterations = policy_engine.max_attempts()
    tried_action = state.get("chosen_action")

    if outcome.get("recovered"):
        with open_session(config) as db:
            recorder.record(db, case_id, "ROUTER_DECISION", payload={"decision": "recovered", "iterations": iterations})
            log_decision(db, case_id=case_id, node_name="router", output={"decision": "recovered"})
        return {"terminal_status": "RECOVERED", "iterations": iterations}

    # Not recovered: rule this action out so the next EV pass picks a different one.
    rejected = list(state.get("rejected_actions", []))
    if tried_action and tried_action not in rejected:
        rejected.append(tried_action)

    exhausted = iterations >= max_iterations
    decision = "stop" if exhausted else "continue"
    with open_session(config) as db:
        recorder.record(
            db,
            case_id,
            "ROUTER_DECISION",
            payload={"decision": decision, "iterations": iterations, "max_iterations": max_iterations},
        )
        log_decision(
            db,
            case_id=case_id,
            node_name="router",
            output={"decision": decision, "iterations": iterations},
            reasoning=f"iteration {iterations}/{max_iterations}",
        )

    update: Dict[str, Any] = {"iterations": iterations, "rejected_actions": rejected}
    if exhausted:
        update["terminal_status"] = "CLOSED_NO_RECOVERY"
    return update
