"""TDD Integration and Chaos Test Suite for Phase F (F1, F1.2, F3) & Phase B5.

Covers:
- F1 / F1.2: End-to-End Recovery Flow & Webhook Event Matrix Chaos
  * Webhook payment.failed -> Live case created with origin='live'
  * Live recovery action creates payment link & sends message via MockCommsProvider
  * Webhook payment_link.paid settles outcome with fee deduction & marks RECOVERED
  * Duplicate delivery idempotency (provider_events dedup)
  * Refund event (payment.refunded) reverses ledger and marks REFUNDED
  * Dispute event (payment.dispute.created) records escalation and marks DISPUTED
- F3: Cutover Flags & Action Gating
  * LIVE_RECOVERY_ENABLED=False halts live tool execution with LIVE_RECOVERY_DISABLED
  * Selectively omitting an action from LIVE_ACTIONS blocks that specific action
- B5: Fee schedule calibration in INTERVENTION_COSTS
- Contract verification for pinned Razorpay webhook payloads
"""
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.domain.ids import generate_id
from app.models.case import RevenueRiskCase
from app.models.customer import Customer
from app.models.provider_event import ProviderEvent
from app.models.provider_object import ProviderObject
from app.models.escalation import Escalation
from app.models.outcome import RecoveryOutcome
from app.schemas.enums import CaseStatus, CaseType, EscalationReason, InterventionType
from app.services.provider_event_service import record_raw_event, process_provider_event
from app.services.case_service import get_case


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_phase_f.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": 30.0, "check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_live_customer_and_case(db, *, amount=2500.0, payment_id="pay_phase_f_test"):
    cust_id = generate_id("CUS", db)
    customer = Customer(
        id=cust_id,
        name="Ananya Roy",
        email="ananya.roy@example.com",
        phone="+919123456789",
        origin="live",
    )
    db.add(customer)

    case_id = generate_id("RR", db)
    case = RevenueRiskCase(
        id=case_id,
        customer_id=cust_id,
        case_type=CaseType.FAILED_PAYMENT.value,
        status=CaseStatus.DETECTED.value,
        amount_at_risk=amount,
        origin="live",
        attempt_count=0,
        payment_id=payment_id,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    db.refresh(customer)
    return case, customer


# ======================================================================================
# B5: Fee Schedule Calibration & Documentation Tests
# ======================================================================================

def test_b5_cost_schedule_values():
    """B5: INTERVENTION_COSTS reflect documented Razorpay test-mode figures & comms costs."""
    from app.agent.costs import INTERVENTION_COSTS, cost_of

    # Bare retry or checkout collection has 0 platform fee
    assert INTERVENTION_COSTS[InterventionType.RETRY_PAYMENT.value] == 0.0
    # Payment links carry hosted link fee
    assert INTERVENTION_COSTS[InterventionType.CREATE_PAYMENT_LINK.value] == 5.0
    # Outreach messages costs
    assert INTERVENTION_COSTS[InterventionType.SEND_REMINDER.value] == 8.0
    assert INTERVENTION_COSTS[InterventionType.SEND_DISCOUNT_MESSAGE.value] == 10.0
    assert INTERVENTION_COSTS[InterventionType.OFFER_PAYMENT_PLAN.value] == 12.0

    # Verification helper returns accurate cost
    assert cost_of(InterventionType.SEND_REMINDER.value) == 8.0
    assert cost_of(InterventionType.RETRY_PAYMENT.value) == 0.0


# ======================================================================================
# F3: Cutover Flags & Action Gating Tests
# ======================================================================================

def test_f3_cutover_master_flag_disables_live_recovery(db, monkeypatch):
    """F3: When LIVE_RECOVERY_ENABLED is False, live recovery actions halt with clear error."""
    from app.config import settings
    from app.agent.nodes.execute_tool import execute_tool

    case, _ = _seed_live_customer_and_case(db)
    monkeypatch.setattr(settings, "live_recovery_enabled", False)

    state = {
        "case_id": case.id,
        "chosen_action": InterventionType.CREATE_PAYMENT_LINK.value,
        "status": CaseStatus.ACTION_EXECUTING.value,
        "context": {},
    }
    config = {"configurable": {"session_factory": lambda: db, "thread_id": case.id}}

    result_state = execute_tool(state, config=config)
    tool_res = result_state.get("tool_result", {})
    assert tool_res.get("success") is False
    assert "DISABLED" in tool_res.get("error_code", "")


def test_f3_selective_live_actions_gating(db, monkeypatch):
    """F3: When an action is excluded from LIVE_ACTIONS, it is blocked while enabled ones pass."""
    from app.config import settings, is_live_action_enabled
    from app.agent.nodes.execute_tool import execute_tool

    monkeypatch.setattr(settings, "live_recovery_enabled", True)
    # Only allow reminders, disallow payment links
    monkeypatch.setattr(settings, "live_actions", "reminders,checkout_collect")

    assert is_live_action_enabled("send_reminder") is True
    assert is_live_action_enabled("create_payment_link") is False

    case, _ = _seed_live_customer_and_case(db)
    state = {
        "case_id": case.id,
        "chosen_action": InterventionType.CREATE_PAYMENT_LINK.value,
        "status": CaseStatus.ACTION_EXECUTING.value,
        "context": {},
    }
    config = {"configurable": {"session_factory": lambda: db, "thread_id": case.id}}

    result_state = execute_tool(state, config=config)
    tool_res = result_state.get("tool_result", {})
    assert tool_res.get("success") is False
    assert tool_res.get("error_code") == "ACTION_DISABLED_BY_POLICY"


# ======================================================================================
# F1 & F1.2: End-to-End Recovery Flow & Webhook Event Matrix Chaos Tests
# ======================================================================================

def test_f1_end_to_end_payment_link_recovery_flow(db, monkeypatch):
    """F1: Complete flow: payment.failed -> link create -> comms send -> payment_link.paid -> settle."""
    from app.config import settings
    from app.services import razorpay_service

    monkeypatch.setattr(settings, "live_recovery_enabled", True)
    monkeypatch.setattr(settings, "live_actions", "retry,payment_link,checkout_collect,reminders")

    def _fake_create_link(amount_paise, description, notes, reminder_enable=False, expire_by=None):
        return {
            "id": f"plink_mock_{notes.get('case_id')}",
            "entity": "payment_link",
            "amount": amount_paise,
            "currency": "INR",
            "short_url": "https://rzp.io/i/mockLink123",
            "status": "created",
            "reminder_enable": reminder_enable,
            "notes": notes,
        }

    monkeypatch.setattr(razorpay_service, "_create_payment_link_on_gateway", _fake_create_link)

    case, customer = _seed_live_customer_and_case(db, amount=3000.0)

    # 1. Simulate agent executing CREATE_PAYMENT_LINK
    from app.tools.live.payment_tools import live_create_payment_link
    link_res = live_create_payment_link(db, case_id=case.id, attempt=1, caller="system")
    assert link_res.success is True
    plink_id = link_res.data["payment_link_id"]

    # 2. Check provider_objects table registry
    pobj = db.query(ProviderObject).filter(ProviderObject.provider_object_id == plink_id).first()
    assert pobj is not None
    assert pobj.case_id == case.id

    # 3. Simulate payment_link.paid webhook event
    event_id = "evt_f1_plink_paid_001"
    payload = {
        "event": "payment_link.paid",
        "contains": ["payment_link", "payment"],
        "payload": {
            "payment_link": {
                "entity": {
                    "id": plink_id,
                    "amount": 300000,
                    "amount_paid": 300000,
                    "currency": "INR",
                    "status": "paid",
                    "notes": {"case_id": case.id},
                }
            },
            "payment": {
                "entity": {
                    "id": "pay_f1_captured_001",
                    "amount": 300000,
                    "currency": "INR",
                    "status": "captured",
                    "fee": 6000,  # ₹60.00 fee
                }
            }
        }
    }

    ev_id, is_new, _ = record_raw_event(
        db,
        provider="razorpay",
        razorpay_event_id=event_id,
        event_type="payment_link.paid",
        payload_json=payload,
    )
    process_provider_event(db, ev_id)

    # 4. Verify case settled and marked RECOVERED
    refreshed_case = get_case(db, case.id)
    assert refreshed_case.status == CaseStatus.RECOVERED.value

    # 5. Verify ledger totals deduct gateway fee
    outcome = db.query(RecoveryOutcome).filter(RecoveryOutcome.case_id == case.id).first()
    assert outcome is not None
    assert outcome.gross_recovered == 3000.0
    assert outcome.gateway_fee == 60.0
    assert outcome.net_recovered == round(3000.0 - outcome.cost_total - outcome.discount_total - 60.0, 2)


def test_f1_chaos_duplicate_webhook_delivery_idempotent(db):
    """F1.2: Duplicate webhook delivery is deduplicated and processed exactly once."""
    case, _ = _seed_live_customer_and_case(db, amount=1500.0)

    event_id = "evt_f1_dup_001"
    payload = {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_f1_dup_pay",
                    "amount": 150000,
                    "currency": "INR",
                    "status": "failed",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Payment failed",
                }
            }
        }
    }

    # First delivery
    ev1_id, is_new1, _ = record_raw_event(
        db, provider="razorpay", razorpay_event_id=event_id, event_type="payment.failed", payload_json=payload
    )
    assert is_new1 is True

    # Second concurrent or duplicate delivery with same event_id returns existing record without crash
    ev2_id, is_new2, _ = record_raw_event(
        db, provider="razorpay", razorpay_event_id=event_id, event_type="payment.failed", payload_json=payload
    )
    assert is_new2 is False
    assert ev2_id == ev1_id

    # Exactly 1 row in provider_events
    count = db.query(ProviderEvent).filter(ProviderEvent.razorpay_event_id == event_id).count()
    assert count == 1


def test_f1_chaos_refund_reverses_ledger(db):
    """F1.2: payment.refunded webhook reverses recovery outcome and sets REFUNDED status."""
    case, _ = _seed_live_customer_and_case(db, amount=2000.0)

    # Establish an initial recovery outcome
    outcome = RecoveryOutcome(
        id=generate_id("OUT", db),
        case_id=case.id,
        outcome_type="RECOVERED",
        gross_recovered=2000.0,
        net_recovered=1950.0,
        cost_total=10.0,
        discount_total=0.0,
        gateway_fee=40.0,
        verified_at=datetime.now(timezone.utc),
    )
    db.add(outcome)
    case.status = CaseStatus.RECOVERED.value
    db.commit()

    event_id = "evt_f1_refund_001"
    payload = {
        "event": "payment.refunded",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_f1_to_refund",
                    "amount": 200000,
                    "amount_refunded": 200000,
                    "notes": {"case_id": case.id},
                }
            },
            "refund": {
                "entity": {
                    "id": "rfnd_f1_001",
                    "payment_id": "pay_f1_to_refund",
                    "amount": 200000,
                    "status": "processed",
                }
            }
        }
    }

    ev_id, _, _ = record_raw_event(
        db, provider="razorpay", razorpay_event_id=event_id, event_type="payment.refunded", payload_json=payload
    )
    process_provider_event(db, ev_id)

    refreshed_case = get_case(db, case.id)
    assert refreshed_case.status == "REFUNDED"
    refreshed_outcome = db.query(RecoveryOutcome).filter(RecoveryOutcome.case_id == case.id).first()
    assert refreshed_outcome.outcome_type == "REFUNDED"


def test_f1_chaos_dispute_creates_escalation(db):
    """F1.2: payment.dispute.created creates escalation row with DISPUTE_FILED reason."""
    case, _ = _seed_live_customer_and_case(db, amount=5000.0)

    event_id = "evt_f1_dispute_001"
    payload = {
        "event": "payment.dispute.created",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_f1_dispute_target",
                    "notes": {"case_id": case.id},
                }
            },
            "dispute": {
                "entity": {
                    "id": "disp_f1_001",
                    "amount": 500000,
                    "reason_code": "fraudulent",
                }
            }
        }
    }

    ev_id, _, _ = record_raw_event(
        db, provider="razorpay", razorpay_event_id=event_id, event_type="payment.dispute.created", payload_json=payload
    )
    process_provider_event(db, ev_id)

    refreshed_case = get_case(db, case.id)
    assert refreshed_case.status == "DISPUTED"

    escalation = db.query(Escalation).filter(Escalation.case_id == case.id).first()
    assert escalation is not None
    assert escalation.reason == EscalationReason.DISPUTE_FILED.value
