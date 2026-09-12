from app.policies.engine import evaluate, APPROVED, REJECTED, ESCALATE
from app.schemas.enums import InterventionType, EscalationReason

TEST_POLICY = {
    "human_approval": {"required_above_amount": 100000},
    "payment": {"retry_window_hours": 72, "max_retries": 3, "min_amount": 1},
    "messaging": {"max_messages_per_case": 3, "minimum_hours_between_messages": 24},
    "discount": {"max_absolute_amount": 1000}
}

def test_discount_over_absolute_limit_rejected():
    res = evaluate(
        InterventionType.SEND_DISCOUNT_MESSAGE.value,
        amount_at_risk=5000,
        attempt_count=0,
        discount_amount=1500.0,
        policy=TEST_POLICY
    )
    assert res.result == REJECTED
    assert res.reason == EscalationReason.POLICY_REJECTION.value

def test_discount_at_limit_approved():
    res = evaluate(
        InterventionType.SEND_DISCOUNT_MESSAGE.value,
        amount_at_risk=5000,
        attempt_count=0,
        discount_amount=1000.0,
        policy=TEST_POLICY
    )
    assert res.result == APPROVED

def test_message_cap_rejected():
    res = evaluate(
        InterventionType.SEND_REMINDER.value,
        amount_at_risk=5000,
        attempt_count=0,
        message_count=3,
        policy=TEST_POLICY
    )
    assert res.result == REJECTED
    assert res.reason == EscalationReason.POLICY_REJECTION.value

def test_message_spacing_rejected():
    res = evaluate(
        InterventionType.SEND_REMINDER.value,
        amount_at_risk=5000,
        attempt_count=0,
        hours_since_last_message=12.0,
        policy=TEST_POLICY
    )
    assert res.result == REJECTED
    assert res.reason == EscalationReason.POLICY_REJECTION.value

def test_retry_window_expired_rejected():
    res = evaluate(
        InterventionType.RETRY_PAYMENT.value,
        amount_at_risk=5000,
        attempt_count=0,
        hours_since_creation=80.0,
        policy=TEST_POLICY
    )
    assert res.result == REJECTED
    assert res.reason == EscalationReason.POLICY_REJECTION.value

def test_amount_threshold_escalates():
    res = evaluate(
        InterventionType.RETRY_PAYMENT.value,
        amount_at_risk=150000.0,
        attempt_count=0,
        policy=TEST_POLICY
    )
    assert res.result == ESCALATE
    assert res.reason == EscalationReason.AMOUNT_EXCEEDS_POLICY.value

def test_retries_exhausted_rejected():
    res = evaluate(
        InterventionType.RETRY_PAYMENT.value,
        amount_at_risk=5000,
        attempt_count=3,
        policy=TEST_POLICY
    )
    assert res.result == REJECTED
    assert res.reason == EscalationReason.MAX_RETRIES_EXCEEDED.value

def test_min_amount_payment_link_rejected():
    res = evaluate(
        InterventionType.CREATE_PAYMENT_LINK.value,
        amount_at_risk=0.5,
        attempt_count=0,
        policy=TEST_POLICY
    )
    assert res.result == REJECTED
    assert res.reason == EscalationReason.POLICY_REJECTION.value
