"""execute_tool node (PRD §17, §38).

Executes the approved action through its idempotent simulated tool, persists the resulting
:class:`~app.models.intervention.Intervention` (the tool does this), and bumps the case's attempt
count. The attempt number used for the tool's idempotency key is the *next* attempt, so replaying a
checkpointed run reuses the same key and never double-charges (§38).
"""
from __future__ import annotations

from typing import Any, Dict

from app.agent.nodes.common import RunnableConfig, log_decision, open_session
from app.audit import recorder
from app.observability import traceable
from app.schemas.enums import CaseStatus
from app.services import case_service
from app.tools.base import ToolResult
from app.tools.payment_tools import TOOL_FOR_ACTION


@traceable(name="node.execute_tool", run_type="chain")
def execute_tool(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    case_id = state["case_id"]
    action = state.get("chosen_action")

    with open_session(config) as db:
        case = case_service.get_case_row(db, case_id)
        payment_id = case.payment_id if case else None
        attempt_number = (case.attempt_count or 0) + 1 if case else 1

        tool = TOOL_FOR_ACTION.get(action)
        if tool is None:
            result = ToolResult(
                tool=str(action), success=False, error_code="NO_TOOL_FOR_ACTION", retryable=False,
                detail=f"no tool registered for action {action}",
            )
        else:
            result = tool(db, case_id=case_id, payment_id=payment_id, attempt=attempt_number)

        # Count the attempt regardless of success (it draws down the retry budget, PRD §16).
        new_attempt = case_service.increment_attempt(db, case_id)
        case_service.set_status(db, case_id, CaseStatus.ACTION_EXECUTING.value)

        result_payload = result.model_dump()
        recorder.record(
            db,
            case_id,
            "TOOL_EXECUTED",
            payload={"action": action, "attempt": attempt_number, **result_payload},
        )
        log_decision(
            db,
            case_id=case_id,
            node_name="execute_tool",
            output={"action": action, "attempt": attempt_number, "result": result_payload},
            reasoning=result.detail,
        )

    return {"tool_result": result_payload, "attempt": new_attempt}
