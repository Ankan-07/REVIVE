from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.models.payment import Payment
from app.schemas.enums import InterventionType, PaymentStatus
from app.simulation.payment_sim import simulate_payment
from app.agent.costs import cost_of

def evaluate_baseline_strategy(db: Session, failed_payments: List[Payment]) -> Dict[str, Any]:
    """
    Evaluates the naive baseline strategy for a set of failed payments.
    Strategy: 1 Retry -> 1 Generic Message (SEND_REMINDER).
    Escalates if still unrecovered and amount > 100,000 INR.
    """
    gross_recovered = 0.0
    net_recovered = 0.0
    recovered_count = 0
    escalation_count = 0
    cost_total = 0.0

    retry_action = InterventionType.RETRY_PAYMENT.value
    reminder_action = InterventionType.SEND_REMINDER.value

    retry_cost = cost_of(retry_action)
    reminder_cost = cost_of(reminder_action)

    for p in failed_payments:
        if p.status != PaymentStatus.FAILED.value:
            continue
            
        case_cost = 0.0
        
        # Step 1: Retry once
        retry_res = simulate_payment(db, payment_id=p.id, action=retry_action, attempt=1)
        case_cost += retry_cost
        
        if retry_res["success"]:
            gross_recovered += p.amount
            net_recovered += (p.amount - case_cost)
            cost_total += case_cost
            recovered_count += 1
            continue
            
        # Step 2: One reminder
        remind_res = simulate_payment(db, payment_id=p.id, action=reminder_action, attempt=1)
        case_cost += reminder_cost
        
        if remind_res["success"]:
            gross_recovered += p.amount
            net_recovered += (p.amount - case_cost)
            cost_total += case_cost
            recovered_count += 1
            continue
            
        # Step 3: Default Escalation rule (e.g. > 100,000)
        cost_total += case_cost
        if p.amount > 100000:
            escalation_count += 1

    return {
        "strategy": "BASELINE",
        "cases_processed": len(failed_payments),
        "recovered_count": recovered_count,
        "escalation_count": escalation_count,
        "gross_recovered": round(gross_recovered, 2),
        "net_recovered": round(net_recovered, 2),
        "cost_total": round(cost_total, 2),
        "recovery_rate": round(recovered_count / max(len(failed_payments), 1), 4),
        "escalation_rate": round(escalation_count / max(len(failed_payments), 1), 4),
    }
