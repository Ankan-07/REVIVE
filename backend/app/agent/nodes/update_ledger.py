"""update_ledger node (PRD §23, §47, §57 — the terminal finalizer).

Reads ``terminal_status`` and writes the case's final books: a :class:`RecoveryOutcome` row (with
net = gross − costs − discounts), the case's ``net_recovered_amount``, the final ``CaseStatus``, and
a closing audit event. This is the single place a case is "closed", so the ledger and timeline always
agree on the ending.
"""
from __future__ import annotations

from typing import Any, Dict

from app.agent.nodes.common import RunnableConfig, log_decision, open_session
from app.audit import recorder
from app.observability import traceable
from app.schemas.enums import CaseStatus, OutcomeType
from app.services import case_service, intervention_service, outcome_service


@traceable(name="node.update_ledger", run_type="chain")
def update_ledger(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    case_id = state["case_id"]
    terminal = state.get("terminal_status") or "CLOSED_NO_RECOVERY"

    with open_session(config) as db:
        case = case_service.get_case_row(db, case_id)
        amount = case.amount_at_risk if case else 0.0
        totals = intervention_service.totals(db, case_id)
        cost_total = totals["cost_total"]
        discount_total = totals["discount_total"]

        gateway_fee_paise = 0
        if terminal == "RECOVERED":
            if state.get("settled_amount") is not None:
                gross = float(state["settled_amount"])
                gateway_fee_paise = int(state.get("gateway_fee_paise") or 0)
            else:
                from app.services import provider_object_service

                pobjs = provider_object_service.list_for_case(db, case_id)
                captured_pobjs = [
                    p for p in pobjs if p.object_type == "payment" and p.status == "captured" and p.amount_paise
                ]
                if captured_pobjs:
                    gross = float(captured_pobjs[-1].amount_paise) / 100.0
                    gateway_fee_paise = int(captured_pobjs[-1].fee_paise or 0)
                else:
                    gross = amount

            if case and case.amount_at_risk and 0 < gross < float(case.amount_at_risk):
                outcome_type = OutcomeType.RECOVERED_PARTIAL.value
            else:
                outcome_type = OutcomeType.RECOVERED_FULL.value
            final_status = CaseStatus.RECOVERED.value
        elif terminal == "ESCALATED":
            gross = 0.0
            outcome_type = OutcomeType.ESCALATED.value
            final_status = CaseStatus.ESCALATED.value
        else:  # CLOSED_NO_RECOVERY
            gross = 0.0
            outcome_type = OutcomeType.FAILED_PERMANENT.value
            final_status = CaseStatus.CLOSED_NO_RECOVERY.value

        outcome = outcome_service.record_outcome(
            db,
            case_id=case_id,
            outcome_type=outcome_type,
            gross_recovered=gross,
            cost_total=cost_total,
            discount_total=discount_total,
            gateway_fee_paise=gateway_fee_paise,
        )

        case_service.set_net_recovered(db, case_id, outcome.net_recovered)
        case_service.set_current_action(db, case_id, None)
        case_service.set_status(db, case_id, final_status)
        recorder.record(
            db,
            case_id,
            terminal,  # RECOVERED | ESCALATED | CLOSED_NO_RECOVERY as the closing event type
            payload={
                "outcome_type": outcome_type,
                "gross_recovered": gross,
                "cost_total": cost_total,
                "discount_total": discount_total,
                "gateway_fee": float(gateway_fee_paise) / 100.0,
                "net_recovered": outcome.net_recovered,
            },
        )
        log_decision(
            db,
            case_id=case_id,
            node_name="update_ledger",
            output={"terminal_status": terminal, "net_recovered": outcome.net_recovered},
            reasoning=f"closed as {final_status}",
        )

    return {}
