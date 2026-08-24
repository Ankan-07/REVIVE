"""diagnose node (PRD §14, §31, §56).

Turns the context snapshot into a structured :class:`~app.agent.contracts.Diagnosis`. Uses the LLM
when a key is configured, otherwise a deterministic heuristic that returns the *same* contract — so
the graph behaves identically offline and every path is traced. Either way the diagnosis is only a
description of *what went wrong*; it never chooses an action (principle §12).
"""
from __future__ import annotations

from typing import Any, Dict

from app.agent.contracts import Diagnosis
from app.agent.llm import LLMUnavailable, is_llm_available, structured_complete
from app.agent.nodes.common import RunnableConfig, configurable, log_decision, open_session
from app.agent.prompts.diagnose import DIAGNOSE_SYSTEM, build_diagnose_user
from app.audit import recorder
from app.config import settings
from app.observability import traceable
from app.services import case_service


def _fallback_diagnosis(context: Dict[str, Any]) -> Diagnosis:
    """Deterministic root-cause guess from the signals, mirroring the LLM's contract."""
    error = (context.get("error_code") or "").lower()
    method_health = context.get("method_health")
    if context.get("gateway_degraded"):
        return Diagnosis(
            type="gateway_degradation",
            confidence=0.7,
            evidence=[
                f"gateway {context.get('gateway')} success rate {context.get('gateway_success_rate')} "
                f"below baseline {context.get('gateway_baseline_rate')}"
            ],
        )
    if "insufficient" in error:
        return Diagnosis(type="insufficient_funds", confidence=0.6, evidence=[f"error_code={error}"])
    if "timeout" in error or "network" in error:
        return Diagnosis(type="network_timeout", confidence=0.55, evidence=[f"error_code={error}"])
    if method_health is not None and method_health < 0.5:
        return Diagnosis(
            type="expired_or_invalid_method",
            confidence=0.5,
            evidence=[f"method_health={method_health}"],
        )
    return Diagnosis(type="unknown", confidence=0.3, evidence=["no strong signal in context"])


@traceable(name="node.diagnose", run_type="chain")
def diagnose(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    case_id = state["case_id"]
    context = state.get("context", {})

    client = configurable(config, "llm_client")
    model = configurable(config, "diagnose_model", settings.diagnosis_llm_model)

    source = "llm"
    try:
        if client is None and not is_llm_available():
            raise LLMUnavailable("no OpenAI key")
        diagnosis = structured_complete(
            Diagnosis,
            system=DIAGNOSE_SYSTEM,
            user=build_diagnose_user(context),
            model=model,
            client=client,
        )
    except Exception:  # LLMUnavailable, validation failure, or any provider error -> deterministic path
        diagnosis = _fallback_diagnosis(context)
        source = "heuristic"

    diagnosis_payload = {**diagnosis.model_dump(), "source": source}
    with open_session(config) as db:
        case_service.set_diagnosis(db, case_id, diagnosis_payload)  # also flips status to DIAGNOSED
        recorder.record(db, case_id, "DIAGNOSIS", payload=diagnosis_payload)
        log_decision(
            db,
            case_id=case_id,
            node_name="diagnose",
            output=diagnosis_payload,
            reasoning="; ".join(diagnosis.evidence),
        )

    return {"diagnosis": diagnosis_payload}
