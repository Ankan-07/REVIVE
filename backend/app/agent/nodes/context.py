"""build_context node (PRD §13).

Assembles the deterministic snapshot the rest of the graph reasons over: the failed payment, the
customer's intent/segment, and the health of the current gateway versus its baseline and the
alternatives. Everything here comes straight from the DB — no LLM, no guessing — so diagnosis and EV
scoring stand on ground truth.
"""
from __future__ import annotations

from typing import Any, Dict

from app.agent.nodes.common import RunnableConfig, log_decision, open_session
from app.audit import recorder
from app.models.customer import Customer
from app.models.metric import GatewayMetric
from app.models.payment import Payment
from app.models.checkout import Checkout
from app.models.invoice import Invoice
from app.models.communication import Communication
from app.observability import traceable
from app.schemas.enums import CaseStatus, CaseType
from app.services import case_service
from app.services.gateway_metric_service import load_gateway_rates

# A gateway is "degraded" once its live success rate falls this far below its own baseline.
_DEGRADATION_MARGIN = 0.05


@traceable(name="node.build_context", run_type="chain")
def build_context(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    case_id = state["case_id"]
    with open_session(config) as db:
        case = case_service.get_case_row(db, case_id)
        if case is None:
            raise LookupError(f"Case {case_id} not found")

        customer = db.query(Customer).filter(Customer.id == case.customer_id).first()

        context: Dict[str, Any] = {
            "case_type": case.case_type,
            "customer_id": case.customer_id,
            "amount_at_risk": case.amount_at_risk,
            "customer_intent": customer.intent_score if customer else None,
            "customer_segment": customer.segment if customer else None,
            "customer_ltv": customer.ltv_amount if customer else None,
        }

        if case.case_type == CaseType.FAILED_PAYMENT.value:
            payment = db.query(Payment).filter(Payment.id == case.payment_id).first()
            rates = load_gateway_rates(db)

            current_gateway = payment.gateway if payment else None
            current_rate = rates.get(current_gateway) if current_gateway else None

            baseline_metric = (
                db.query(GatewayMetric)
                .filter(GatewayMetric.gateway_name == current_gateway)
                .order_by(GatewayMetric.recorded_at.desc())
                .first()
                if current_gateway
                else None
            )
            baseline_rate = baseline_metric.baseline_success_rate if baseline_metric else None
            degraded = (
                current_rate is not None
                and baseline_rate is not None
                and current_rate < baseline_rate - _DEGRADATION_MARGIN
            )

            context.update({
                "payment_id": case.payment_id,
                "currency": payment.currency if payment else None,
                "error_code": payment.error_code if payment else None,
                "gateway": current_gateway,
                "gateway_success_rate": current_rate,
                "gateway_baseline_rate": baseline_rate,
                "gateway_degraded": bool(degraded),
                "method_health": payment.method_health if payment else None,
                "alternative_gateways": {g: r for g, r in rates.items() if g != current_gateway},
            })
            
        elif case.case_type == CaseType.ABANDONED_CHECKOUT.value:
            checkout = db.query(Checkout).filter(
                Checkout.customer_id == case.customer_id, 
                Checkout.status == "ABANDONED"
            ).order_by(Checkout.created_at.desc()).first()
            
            context.update({
                "checkout_id": checkout.id if checkout else None,
                "cart_value": checkout.cart_value if checkout else None,
                "items": checkout.items_json if checkout else None,
                "abandoned_at": checkout.abandoned_at.isoformat() if checkout and checkout.abandoned_at else None,
            })

        elif case.case_type == CaseType.OVERDUE_INVOICE.value:
            invoice = db.query(Invoice).filter(
                Invoice.customer_id == case.customer_id, 
                Invoice.status == "OVERDUE"
            ).order_by(Invoice.created_at.desc()).first()
            
            communications = db.query(Communication).filter(
                Communication.case_id == case.id
            ).order_by(Communication.sent_at.asc()).all()

            context.update({
                "invoice_id": invoice.id if invoice else None,
                "due_date": invoice.due_date.isoformat() if invoice and invoice.due_date else None,
                "invoice_amount": invoice.amount if invoice else None,
                "communications": [{"channel": c.channel, "content": c.content, "sent_at": c.sent_at.isoformat()} for c in communications],
            })

        case_service.set_status(db, case_id, CaseStatus.CONTEXT_BUILT.value)
        recorder.record(db, case_id, "CONTEXT_BUILT", payload=context)
        log_decision(db, case_id=case_id, node_name="build_context", output=context)

    return {"context": context}
