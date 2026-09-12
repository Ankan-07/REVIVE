"""Tests for the Phase 4 recovery agent (LangGraph state machine · PRD §10–23, §38, §47, §56).

All tests are hermetic and fully offline:

* An autouse fixture blanks the OpenAI/LangSmith keys and clears the cached tracing/client so a
  developer's local ``.env`` can never make the suite hit the network. With no OpenAI key the
  reasoning nodes take their deterministic fallback; with no LangSmith key ``@traceable`` is a no-op.
* Graph runs use an in-memory SQLite DB behind a ``StaticPool`` (so every short-lived node session
  shares one DB) and a ``MemorySaver`` checkpointer (so nothing touches the durable checkpoint file).
* Where a test needs the LLM path (a specific candidate set, or the structured-output retry), it
  injects a fake client whose ``chat.completions.create`` returns canned JSON — exercising the real
  ``structured_complete`` + planner-filtering code without a provider.

The decision core is deterministic, so every recovery/EV assertion is exact, not approximate.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db, get_session_factory
import app.models  # noqa: F401  -- registers every table on Base.metadata for create_all
from app.agent.contracts import Diagnosis
from app.agent.llm import structured_complete
from app.agent.runner import run_agent
from app.api.cases import get_checkpointer
from app.main import app
from app.models.audit import AuditEvent
from app.models.case import RevenueRiskCase
from app.models.customer import Customer
from app.models.intervention import Intervention
from app.models.metric import GatewayMetric
from app.models.outcome import RecoveryOutcome
from app.models.payment import Payment
from app.schemas.enums import CaseStatus, InterventionType, OutcomeType, PaymentStatus
from app.tools.payment_tools import retry_payment


# --------------------------------------------------------------------------------------------------
# Hermetic environment + DB fixtures
# --------------------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    """Force fully-offline runs regardless of any local ``.env``.

    Blanking the keys (rather than deleting them) means ``load_dotenv`` — which never overrides a
    key already present in the environment — cannot re-populate them from disk. Clearing the caches
    makes the guard take effect even if a prior test already resolved them.
    """
    for var in ("OPENAI_API_KEY", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"):
        monkeypatch.setenv(var, "")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")

    from app.agent import llm
    from app import observability

    observability.configure_tracing.cache_clear()
    llm.get_client.cache_clear()
    yield


def _new_engine():
    """A shared-connection in-memory engine so every node's short-lived session sees one DB."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def factory():
    """A session factory bound to a fresh in-memory DB (the graph nodes open sessions from this)."""
    engine = _new_engine()
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _run(session_factory, case_id, llm_client=None):
    """Drive one case through the graph with a hermetic in-memory checkpointer."""
    return run_agent(
        case_id,
        session_factory=session_factory,
        checkpointer=MemorySaver(),
        llm_client=llm_client,
    )


# --------------------------------------------------------------------------------------------------
# A fake OpenAI client for the LLM-path tests
# --------------------------------------------------------------------------------------------------
class _Completions:
    """Stand-in for ``client.chat.completions`` that returns canned content and counts calls."""

    def __init__(self, responder):
        self._responder = responder
        self.calls = 0

    def create(self, *, model, messages, response_format=None, **kwargs):
        self.calls += 1
        content = self._responder(messages, self.calls)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class FakeLLM:
    """Duck-typed OpenAI client: exposes ``.chat.completions.create`` like the real SDK."""

    def __init__(self, responder):
        self.completions = _Completions(responder)
        self.chat = SimpleNamespace(completions=self.completions)


def _diagnose_then_plan(plan_json: dict):
    """Responder that serves a gateway-degradation diagnosis, then the given plan.

    Discriminates on the system prompt: the planner's system message contains "planning stage",
    the diagnoser's contains "diagnosis stage".
    """
    diagnosis_json = {
        "type": "gateway_degradation",
        "confidence": 0.8,
        "evidence": ["current gateway success rate is below its baseline"],
    }

    def responder(messages, _call):
        system = messages[0]["content"]
        if "planning stage" in system:
            return json.dumps(plan_json)
        return json.dumps(diagnosis_json)

    return responder


# --------------------------------------------------------------------------------------------------
# Seed helpers — a degraded current gateway (PAYU) with healthy alternatives (STRIPE/RAZORPAY)
# --------------------------------------------------------------------------------------------------
def _seed_gateways(db):
    db.add_all(
        [
            GatewayMetric(id="GWM-00001", gateway_name="PAYU", success_rate=0.50,
                          baseline_success_rate=0.97, latency_ms=1200.0, health_status="DEGRADED"),
            GatewayMetric(id="GWM-00002", gateway_name="STRIPE", success_rate=0.95,
                          baseline_success_rate=0.97, latency_ms=120.0, health_status="HEALTHY"),
            GatewayMetric(id="GWM-00003", gateway_name="RAZORPAY", success_rate=0.93,
                          baseline_success_rate=0.96, latency_ms=140.0, health_status="HEALTHY"),
        ]
    )


def _seed_case(
    db,
    *,
    amount=5000.0,
    recovery_roll=0.10,
    method_health=1.0,
    intent=1.0,
    attempt_count=0,
    status=CaseStatus.DETECTED.value,
):
    """One VIP customer, one FAILED payment on the degraded gateway, and its DETECTED case."""
    _seed_gateways(db)
    db.add(Customer(id="CUS-00001", name="Alice", email="a@example.com", segment="VIP",
                    ltv_amount=8000.0, risk_score=0.2, intent_score=intent))
    db.add(Payment(id="PAY-00001", customer_id="CUS-00001", amount=amount, currency="INR",
                   gateway="PAYU", status=PaymentStatus.FAILED.value, error_code="timeout",
                   attempt_count=0, method_health=method_health, recovery_roll=recovery_roll))
    db.add(RevenueRiskCase(id="RR-00001", customer_id="CUS-00001", payment_id="PAY-00001",
                           case_type="FAILED_PAYMENT", status=status, amount_at_risk=amount,
                           priority="HIGH", risk_score=0.6, attempt_count=attempt_count))
    db.commit()
    return "RR-00001"


def _event_types(db, case_id):
    rows = (
        db.query(AuditEvent)
        .filter(AuditEvent.case_id == case_id)
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        .all()
    )
    return [r.event_type for r in rows]


# --------------------------------------------------------------------------------------------------
# 1. Switch-gateway decision + end-to-end RECOVERED (LLM proposes {switch, retry}; EV disposes)
# --------------------------------------------------------------------------------------------------
def test_switch_gateway_recovers_end_to_end(factory):
    db = factory()
    case_id = _seed_case(db, amount=5000.0, recovery_roll=0.10)
    db.close()

    # Planner proposes only switch + retry (no payment link), so the deterministic EV scorer's
    # argmax legitimately lands on SWITCH_GATEWAY (5000×0.95−20=4730 > retry 5000×0.50−0=2500).
    plan_json = {
        "candidate_actions": [
            {"action": "SWITCH_GATEWAY", "expected_recovery_probability": 0.9,
             "estimated_cost": 20, "rationale": "current gateway degraded; healthy alternative exists"},
            {"action": "RETRY_PAYMENT", "expected_recovery_probability": 0.5,
             "estimated_cost": 0, "rationale": "cheap same-rail retry as fallback"},
        ],
        "reasoning_summary": "switch to a healthy gateway first, retry as a cheap fallback",
    }
    llm = FakeLLM(_diagnose_then_plan(plan_json))

    final = _run(factory, case_id, llm_client=llm)

    assert final["chosen_action"] == InterventionType.SWITCH_GATEWAY.value
    assert final["terminal_status"] == "RECOVERED"

    db = factory()
    try:
        case = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == case_id).first()
        assert case.status == CaseStatus.RECOVERED.value
        assert case.diagnosis_json["source"] == "llm"          # the injected planner path was used
        assert case.diagnosis_json["type"] == "gateway_degradation"
        assert case.current_action is None                     # cleared on close

        # Exactly one intervention (the switch); net = gross − cost = 5000 − 20.
        interventions = db.query(Intervention).filter(Intervention.case_id == case_id).all()
        assert len(interventions) == 1
        assert interventions[0].intervention_type == InterventionType.SWITCH_GATEWAY.value

        outcome = db.query(RecoveryOutcome).filter(RecoveryOutcome.case_id == case_id).first()
        assert outcome.outcome_type == OutcomeType.RECOVERED_FULL.value
        assert outcome.net_recovered == pytest.approx(4980.0)
        assert case.net_recovered_amount == pytest.approx(4980.0)

        # The audit timeline reads as one continuous history from context through recovery.
        events = _event_types(db, case_id)
        for expected in ("CONTEXT_BUILT", "DIAGNOSIS", "PLAN", "EV_SCORED",
                         "POLICY_CHECK", "TOOL_EXECUTED", "OUTCOME_OBSERVED",
                         "ROUTER_DECISION", "RECOVERED"):
            assert expected in events, f"missing {expected} in {events}"
    finally:
        db.close()


# --------------------------------------------------------------------------------------------------
# 2. Policy escalates a high-value case before any tool runs (PRD §22)
# --------------------------------------------------------------------------------------------------
def test_high_value_case_escalates_without_executing(factory):
    db = factory()
    case_id = _seed_case(db, amount=150_000.0)  # above the ₹1,00,000 human-approval threshold
    db.close()

    final = _run(factory, case_id)  # deterministic fallback (no LLM key)

    # The run pauses at the escalation boundary (interrupt_before=["escalation_pause"]) for an
    # operator; the case is not auto-closed in the same run (test_escalations covers the resume).
    assert final["terminal_status"] is None

    db = factory()
    try:
        case = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == case_id).first()
        assert case.status == CaseStatus.ESCALATED.value
        assert case.attempt_count == 0                                   # nothing was attempted

        assert db.query(Intervention).filter(Intervention.case_id == case_id).count() == 0
        assert "TOOL_EXECUTED" not in _event_types(db, case_id)

        # No closing ledger entry yet — update_ledger runs after the operator approves/rejects.
        assert db.query(RecoveryOutcome).filter(RecoveryOutcome.case_id == case_id).count() == 0

        # A first-class escalation ticket was created for the queue.
        from app.models.escalation import Escalation
        esc = db.query(Escalation).filter(Escalation.case_id == case_id).first()
        assert esc is not None and esc.status == "OPEN"

        # The escalation is recorded as a first-class policy decision, not a failure.
        policy_rows = (
            db.query(AuditEvent)
            .filter(AuditEvent.case_id == case_id, AuditEvent.event_type == "POLICY_CHECK")
            .all()
        )
        assert any((r.payload_json or {}).get("result") == "ESCALATE" for r in policy_rows)
    finally:
        db.close()


# --------------------------------------------------------------------------------------------------
# 3. Retry budget already exhausted -> every action rejected -> CLOSED_NO_RECOVERY (PRD §16, §21)
# --------------------------------------------------------------------------------------------------
def test_exhausted_retry_budget_closes_without_recovery(factory):
    db = factory()
    # max_retries is 3; a case already at 3 attempts must have every payment action rejected.
    case_id = _seed_case(db, amount=5000.0, attempt_count=3)
    db.close()

    final = _run(factory, case_id)

    assert final["terminal_status"] == "CLOSED_NO_RECOVERY"

    db = factory()
    try:
        case = db.query(RevenueRiskCase).filter(RevenueRiskCase.id == case_id).first()
        assert case.status == CaseStatus.CLOSED_NO_RECOVERY.value
        assert case.attempt_count == 3                                    # no new attempt executed

        assert db.query(Intervention).filter(Intervention.case_id == case_id).count() == 0
        assert "TOOL_EXECUTED" not in _event_types(db, case_id)

        outcome = db.query(RecoveryOutcome).filter(RecoveryOutcome.case_id == case_id).first()
        assert outcome.outcome_type == OutcomeType.FAILED_PERMANENT.value
        assert case.net_recovered_amount == pytest.approx(0.0)

        # Every candidate was rejected by policy (max-retries), which is what converges the loop.
        policy_rows = (
            db.query(AuditEvent)
            .filter(AuditEvent.case_id == case_id, AuditEvent.event_type == "POLICY_CHECK")
            .all()
        )
        assert policy_rows and all((r.payload_json or {}).get("result") == "REJECTED" for r in policy_rows)
    finally:
        db.close()


# --------------------------------------------------------------------------------------------------
# 4. structured_complete retries once on invalid JSON, then validates (PRD §31, §56)
# --------------------------------------------------------------------------------------------------
def test_structured_complete_retries_then_validates():
    valid = json.dumps({"type": "insufficient_funds", "confidence": 0.6, "evidence": ["error_code"]})

    def responder(messages, call):
        return "this is not json" if call == 1 else valid  # first call bad, second call good

    client = FakeLLM(responder)
    result = structured_complete(
        Diagnosis, system="diagnosis stage", user="signals", model="gpt-4o", client=client,
    )

    assert isinstance(result, Diagnosis)
    assert result.type == "insufficient_funds"
    assert client.completions.calls == 2  # it retried exactly once with a corrective message


# --------------------------------------------------------------------------------------------------
# 5. Tools are idempotent on the case:action:attempt key (PRD §38)
# --------------------------------------------------------------------------------------------------
def test_tool_is_idempotent_on_repeat(factory):
    db = factory()
    _seed_case(db, amount=5000.0)  # payment on PAYU; we call the retry tool directly below
    # Retry runs on the current (degraded) gateway, but idempotency holds regardless of outcome.

    first = retry_payment(db, case_id="RR-00001", payment_id="PAY-00001", attempt=1)
    second = retry_payment(db, case_id="RR-00001", payment_id="PAY-00001", attempt=1)

    assert first.success == second.success                      # replay returns the prior outcome
    assert "idempotent replay" in second.detail

    rows = db.query(Intervention).filter(Intervention.case_id == "RR-00001").all()
    assert len(rows) == 1                                        # no second side effect
    assert (rows[0].payload_json or {})["idempotency_key"] == "RR-00001:RETRY_PAYMENT:1"
    db.close()


# --------------------------------------------------------------------------------------------------
# 6. Full stack: real POST /events/ creates the case, real POST /cases/{id}/run-agent recovers it
# --------------------------------------------------------------------------------------------------
@pytest.fixture
def api_client():
    """TestClient wired to one in-memory DB, with the agent's factory/checkpointer overridden."""
    engine = _new_engine()
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    api_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    app.dependency_overrides[get_db] = lambda: session               # the /events/ handler session
    app.dependency_overrides[get_session_factory] = lambda: api_factory  # the agent's node sessions
    app.dependency_overrides[get_checkpointer] = lambda: MemorySaver()   # hermetic checkpointer
    client = TestClient(app)
    try:
        yield session, client
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_full_stack_detect_then_run_agent_recovers(api_client):
    session, client = api_client
    _seed_gateways(session)
    # Use canonical 5-digit IDs so the Task-5.1 parameter-validation layer accepts them.
    session.add(Customer(id="CUS-00001", name="Bob", email="b@example.com", segment="VIP",
                         ltv_amount=9000.0, risk_score=0.2, intent_score=1.0))
    session.add(Payment(id="PAY-00001", customer_id="CUS-00001", amount=5000.0, currency="INR",
                        gateway="PAYU", status=PaymentStatus.FAILED.value, error_code="timeout",
                        attempt_count=0, method_health=1.0, recovery_roll=0.10))
    session.commit()

    # Real event route creates the case (DETECTED).
    created = client.post("/events/", json={
        "event_type": "PAYMENT_FAILED",
        "customer_id": "CUS-00001",
        "payment_id": "PAY-00001",
        "amount": 5000.0,
        "currency": "INR",
    })
    assert created.status_code == 200
    case_id = created.json()["case_id"]

    # Real run-agent route drives it to a verified recovery (fallback picks the payment link:
    # p=0.95 via STRIPE, net = 5000 − 5 = 4995).
    resp = client.post(f"/cases/{case_id}/run-agent")
    assert resp.status_code == 200

    body = resp.json()
    assert body["status"] == "RECOVERED"
    assert body["recovered"] is True
    assert body["chosen_action"] == InterventionType.CREATE_PAYMENT_LINK.value
    assert body["outcome_type"] == OutcomeType.RECOVERED_FULL.value
    assert body["net_recovered"] == pytest.approx(4995.0)
    assert any(entry["event_type"] == "RECOVERED" for entry in body["timeline"])
