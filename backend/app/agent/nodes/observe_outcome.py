"""observe_outcome node (PRD §19, §56 — verify, never assume).

The agent must not conclude "recovered" from an in-memory flag. This node re-reads the persisted
intervention for the action/attempt just executed and takes the recovery decision from the row that
is actually in the database. Because the tools don't mutate the ``Payment`` row (the oracle is
read-only), the intervention's stored ``success`` is the authoritative, verifiable signal.
"""
from __future__ import annotations

from typing import Any, Dict

from app.agent.nodes.common import RunnableConfig, log_decision, open_session
from app.audit import recorder
from app.observability import traceable
from app.services import intervention_service
from app.tools.base import idempotency_key


@traceable(name="node.observe_outcome", run_type="chain")
def observe_outcome(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    case_id = state["case_id"]
    tool_result = state.get("tool_result") or {}
    data = tool_result.get("data", {})
    action = data.get("action", state.get("chosen_action"))
    attempt = data.get("attempt")
    injected_outcome = state.get("outcome") or {}

    with open_session(config) as db:
        intervention = None
        if action is not None and attempt is not None:
            key = idempotency_key(case_id, action, attempt)
            intervention = intervention_service.get_by_idempotency_key(db, case_id, key)

        payload = (intervention.payload_json or {}) if intervention else {}

        # If outcome was injected by webhook or timeout resumption, respect that authoritative signal
        if "recovered" in injected_outcome:
            recovered = bool(injected_outcome["recovered"])
            verified_via = injected_outcome.get("verified_via", "webhook_or_timeout")
        else:
            recovered = bool(payload.get("success"))
            verified_via = "intervention_row"

        outcome = {
            "recovered": recovered,
            "action": action,
            "attempt": attempt,
            "intervention_id": intervention.id if intervention else None,
            "probability": payload.get("probability"),
            "gateway_used": payload.get("gateway_used"),
            "verified_via": verified_via,
            **{k: v for k, v in injected_outcome.items() if k not in ("action", "attempt")},
        }

        recorder.record(db, case_id, "OUTCOME_OBSERVED", payload=outcome)
        log_decision(
            db,
            case_id=case_id,
            node_name="observe_outcome",
            output=outcome,
            reasoning=f"verified recovery signal ({verified_via})",
        )

    return {"outcome": outcome}

