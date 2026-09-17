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
from app.schemas.enums import CaseStatus, CaseType
from app.services import case_service
from app.tools.base import ToolResult
from app.tools import TOOL_FOR_ACTION


@traceable(name="node.execute_tool", run_type="chain")
def execute_tool(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    # runner.py sets thread_id=case_id; @traceable can corrupt state["case_id"] (injecting a
    # LangSmith run_id) in the full-stack API test, so we prefer the config thread_id.
    configurable = (config or {}).get("configurable", {})
    case_id = configurable.get("thread_id") or state["case_id"]
    action = state.get("chosen_action")

    with open_session(config) as db:
        case = case_service.get_case_row(db, case_id)
        attempt_number = (case.attempt_count or 0) + 1 if case else 1
        caller = configurable.get("caller") or state.get("caller") or "system"
        
        context = state.get("context", {})
        kwargs = {
            "case_id": case_id,
            "attempt": attempt_number,
            "caller": caller,
        }
        
        if case and case.case_type == CaseType.FAILED_PAYMENT.value:
            kwargs["payment_id"] = context.get("payment_id") or case.payment_id
        elif case and case.case_type == CaseType.ABANDONED_CHECKOUT.value:
            kwargs["checkout_id"] = context.get("checkout_id")
        elif case and case.case_type == CaseType.OVERDUE_INVOICE.value:
            kwargs["invoice_id"] = context.get("invoice_id")

        from app.config import is_live_action_enabled, settings
        from app.tools.live import LIVE_TOOL_FOR_ACTION

        is_live = bool(case and getattr(case, "origin", "lab") == "live")
        if is_live:
            if not getattr(settings, "live_recovery_enabled", False):
                result = ToolResult(
                    tool=str(action),
                    success=False,
                    error_code="LIVE_RECOVERY_DISABLED",
                    retryable=False,
                    detail="Live recovery is disabled via LIVE_RECOVERY_ENABLED=False",
                )
            elif not is_live_action_enabled(str(action)):
                result = ToolResult(
                    tool=str(action),
                    success=False,
                    error_code="ACTION_DISABLED_BY_POLICY",
                    retryable=False,
                    detail=f"Live action '{action}' is disabled by LIVE_ACTIONS policy",
                )
            else:
                tool = LIVE_TOOL_FOR_ACTION.get(action)
                if tool is None:
                    result = ToolResult(
                        tool=str(action), success=False, error_code="NO_TOOL_FOR_ACTION", retryable=False,
                        detail=f"no live tool registered for action {action}",
                    )
                else:
                    result = tool(db, **kwargs)
        else:
            tool = TOOL_FOR_ACTION.get(action)
            if tool is None:
                result = ToolResult(
                    tool=str(action), success=False, error_code="NO_TOOL_FOR_ACTION", retryable=False,
                    detail=f"no simulated tool registered for action {action}",
                )
            else:
                result = tool(db, **kwargs)

        # Count the attempt regardless of success (it draws down the retry budget, PRD §16).
        new_attempt = case_service.increment_attempt(db, case_id)

        result_payload = result.model_dump(mode="json")
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

        await_outcome = False
        if is_live and result.success:
            await_outcome = True
            case_service.set_status(db, case_id, CaseStatus.WAITING_FOR_OUTCOME.value)
            recorder.record(
                db,
                case_id,
                "WAITING_FOR_OUTCOME",
                payload={"action": action, "attempt": attempt_number, "tool_result": result_payload},
            )
        else:
            case_service.set_status(db, case_id, CaseStatus.ACTION_EXECUTING.value)

    return {"tool_result": result_payload, "attempt": new_attempt, "await_outcome": await_outcome}

