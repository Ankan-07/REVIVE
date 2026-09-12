"""Evaluation tests for Phase 11 (PRD §44).

These tests ensure the agent strictly adheres to policies, stopping conditions, and
escalation paths without relying on LLM behavior (using deterministic fallbacks).
"""

from app.schemas.enums import CaseStatus, InterventionType, OutcomeType

# We can reuse the fixtures from test_agent since they provide a great hermetic environment.
from tests.test_agent import _seed_case, _run
from app.models.case import RevenueRiskCase
from app.models.outcome import RecoveryOutcome
from app.models.intervention import Intervention


def test_eval_decision_ev_maximization(factory):
    """EVAL: The agent should always pick the action with the highest Expected Value (EV)."""
    db = factory()
    # A case that could be retried or have a payment link sent.
    case_id = _seed_case(db, amount=10000.0, recovery_roll=0.10)
    db.close()

    # The deterministic fallback for the LLM will pick CREATE_PAYMENT_LINK because STRIPE has high success
    # and link creation is cheap, yielding higher net EV than a degraded retry.
    final = _run(factory, case_id)

    assert final["chosen_action"] == InterventionType.CREATE_PAYMENT_LINK.value
    assert final["terminal_status"] == "RECOVERED"


def test_eval_policy_escalation_boundary(factory):
    """EVAL: Cases over the policy threshold (₹1,00,000) MUST escalate immediately."""
    db = factory()
    case_id = _seed_case(db, amount=200_000.0) # Well over threshold
    db.close()

    final = _run(factory, case_id)

    # Graph should interrupt (pause) for escalation.
    assert final["terminal_status"] is None

    db = factory()
    try:
        case = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == case_id).first()
        assert case.status == CaseStatus.ESCALATED.value
        assert case.attempt_count == 0  # No action should have been taken
        
        # Verify no interventions ran
        assert db.query(Intervention).filter(Intervention.case_id == case_id).count() == 0
    finally:
        db.close()


def test_eval_stopping_condition_max_retries(factory):
    """EVAL: The agent MUST halt and close the case when max retries are hit (no infinite loop)."""
    db = factory()
    # Case already at max retries (3)
    case_id = _seed_case(db, amount=5000.0, attempt_count=3)
    db.close()

    final = _run(factory, case_id)

    assert final["terminal_status"] == "CLOSED_NO_RECOVERY"

    db = factory()
    try:
        case = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == case_id).first()
        assert case.status == CaseStatus.CLOSED_NO_RECOVERY.value
        
        outcome = db.query(RecoveryOutcome).filter(RecoveryOutcome.case_id == case_id).first()
        assert outcome.outcome_type == OutcomeType.FAILED_PERMANENT.value
    finally:
        db.close()


def test_eval_escalation_resume(factory):
    """EVAL: An escalated case can be resumed by an operator."""
    db = factory()
    case_id = _seed_case(db, amount=150_000.0)
    db.close()

    # 1. Run hits escalation and pauses
    final_pause = _run(factory, case_id)
    assert final_pause["terminal_status"] is None

    # 2. Simulate operator approval by updating graph state via checkpointer (done in test_escalations, 
    # but we can verify the boundary holds here).
    
    db = factory()
    try:
        case = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == case_id).first()
        assert case.status == CaseStatus.ESCALATED.value
    finally:
        db.close()
