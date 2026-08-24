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
from app.schemas.enums import CaseStatus
from app.services import case_service, intervention_service
from app.tools.base import idempotency_key


@traceable(name="node.observe_outcome", run_type="chain")
def observe_outcome(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    case_id = state["case_id"]
    tool_result = state.get("tool_result") or {}
    data = tool_result.get("data", {})
    action = data.get("action", state.get("chosen_action"))
    attempt = data.get("attempt")

    with open_session(config) as db:
        intervention = None
        if action is not None and attempt is not None:
            key = idempotency_key(case_id, action, attempt)
            intervention = intervention_service.get_by_idempotency_key(db, case_id, key)

        payload = (intervention.payload_json or {}) if intervention else {}
        recovered = bool(payload.get("success"))

        outcome = {
            "recovered": recovered,
            "action": action,
            "attempt": attempt,
            "intervention_id": intervention.id if intervention else None,
            "probability": payload.get("probability"),
            "gateway_used": payload.get("gateway_used"),
            "verified_via": "intervention_row",
        }

        case_service.set_status(db, case_id, CaseStatus.WAITING_FOR_OUTCOME.value)
        recorder.record(db, case_id, "OUTCOME_OBSERVED", payload=outcome)
        log_decision(
            db,
            case_id=case_id,
            node_name="observe_outcome",
            output=outcome,
            reasoning="verified recovery flag read back from persisted intervention",
        )

    return {"outcome": outcome}
