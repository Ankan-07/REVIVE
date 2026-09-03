"""plan node (PRD §15, §31).

Proposes a candidate set of recovery actions. It first computes, deterministically, the simulator's
recovery probability and fixed cost for each *allowed* action — the menu (see
:func:`app.agent.menu.allowed_menu`) is the ground truth the EV scorer will use. The LLM (or the
fallback) then ranks candidates from that menu. The model's own numbers are advisory only; the menu
and the later EV recomputation are authoritative (principle §12/§47).
"""
from __future__ import annotations

from typing import Any, Dict

from app.agent.contracts import CandidateAction, RecoveryPlan
from app.agent.llm import LLMUnavailable, is_llm_available, structured_complete
from app.agent.menu import allowed_menu
from app.agent.nodes.common import RunnableConfig, configurable, log_decision, open_session
from app.agent.prompts.plan import PLAN_SYSTEM, build_plan_user
from app.audit import recorder
from app.config import settings
from app.observability import traceable
from app.schemas.enums import CaseStatus
from app.services import case_service


def _fallback_plan(menu: list) -> RecoveryPlan:
    """Seed candidates directly from the simulator menu, best-probability first."""
    ordered = sorted(menu, key=lambda m: m["simulator_probability"], reverse=True)
    return RecoveryPlan(
        candidate_actions=[
            CandidateAction(
                action=m["action"],
                expected_recovery_probability=m["simulator_probability"],
                estimated_cost=m["cost"],
                rationale="seeded from simulator menu",
            )
            for m in ordered
        ],
        reasoning_summary="deterministic fallback plan from simulator probabilities",
    )


@traceable(name="node.plan", run_type="chain")
def plan(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    case_id = state["case_id"]
    context = state.get("context", {})
    diagnosis = state.get("diagnosis", {})

    client = configurable(config, "llm_client")
    model = configurable(config, "plan_model", settings.diagnosis_llm_model)

    with open_session(config) as db:
        case_row = case_service.get_case_row(db, case_id)
        menu = allowed_menu(db, case_row, context) if case_row else []

        source = "llm"
        try:
            if client is None and not is_llm_available():
                raise LLMUnavailable("no OpenAI key")
            recovery_plan = structured_complete(
                RecoveryPlan,
                system=PLAN_SYSTEM,
                user=build_plan_user(diagnosis, menu, context),
                model=model,
                client=client,
            )
            # Keep only candidates that name an allowed action; fall back if none survive.
            allowed = {m["action"] for m in menu}
            recovery_plan.candidate_actions = [
                c for c in recovery_plan.candidate_actions if c.action in allowed
            ]
            if not recovery_plan.candidate_actions:
                raise ValueError("planner returned no allowed actions")
        except Exception:  # unavailable, invalid, or empty -> deterministic menu
            recovery_plan = _fallback_plan(menu)
            source = "heuristic"

        candidates = [c.model_dump() for c in recovery_plan.candidate_actions]

        case_service.set_status(db, case_id, CaseStatus.PLANNING.value)
        recorder.record(
            db,
            case_id,
            "PLAN",
            payload={"candidates": candidates, "source": source, "menu": menu},
        )
        log_decision(
            db,
            case_id=case_id,
            node_name="plan",
            output={"candidates": candidates},
            reasoning=recovery_plan.reasoning_summary,
        )

    return {"candidates": candidates, "reasoning_summary": recovery_plan.reasoning_summary}
