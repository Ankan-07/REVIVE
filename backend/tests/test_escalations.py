import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from app.db import Base, get_db, get_session_factory
import app.models  # noqa: F401
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.case import RevenueRiskCase
from app.models.escalation import Escalation
from app.models.audit import AuditEvent
from app.schemas.enums import CaseStatus
from app.api.cases import get_checkpointer
from app.agent.runner import run_agent
from app.main import app

@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture
def db_session(factory):
    session = factory()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def checkpointer():
    return MemorySaver()

@pytest.fixture
def client(factory, checkpointer):
    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.dependency_overrides[get_checkpointer] = lambda: checkpointer
    yield TestClient(app)
    app.dependency_overrides.clear()

@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    """Force fully-offline runs regardless of any local ``.env``."""
    for var in ("OPENAI_API_KEY", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"):
        monkeypatch.setenv(var, "")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")

    from app.agent import llm
    from app import observability
    observability.configure_tracing.cache_clear()
    llm.get_client.cache_clear()
    yield

def test_high_value_escalation_flow(db_session, factory, checkpointer, client):
    # 1. Seed a case with > 100k amount
    from app.models.metric import GatewayMetric
    db_session.add(GatewayMetric(id="GM-1", gateway_name="PAYU", success_rate=1.0, latency_ms=100))
    db_session.add(Customer(id="CUS-99999", name="Escalation Test", email="esc@example.com", intent_score=1.0))
    db_session.add(Payment(id="PAY-99999", customer_id="CUS-99999", amount=150000.0, gateway="PAYU", status="failed", recovery_roll=0.0))
    db_session.add(RevenueRiskCase(
        id="RR-99999", customer_id="CUS-99999", payment_id="PAY-99999", case_type="FAILED_PAYMENT", 
        amount_at_risk=150000.0, status="DETECTED"
    ))
    db_session.commit()

    # 2. Run the agent (will pause at ESCALATED)
    res = run_agent(
        "RR-99999", 
        session_factory=factory, 
        checkpointer=checkpointer
    )

    assert res.get("terminal_status") is None
    
    # Verify the database state
    db_session.expire_all()
    case = db_session.query(RevenueRiskCase).filter_by(id="RR-99999").first()
    assert case.status == CaseStatus.ESCALATED.value

    # Verify escalation ticket was created
    esc = db_session.query(Escalation).filter_by(case_id="RR-99999").first()
    assert esc is not None
    assert esc.status == "OPEN"
    assert esc.reason == "AMOUNT_EXCEEDS_POLICY"

    # 3. Use the frontend API to approve the escalation
    resp = client.post(
        f"/escalations/{esc.id}/resolve",
        json={"resolution_status": "APPROVED", "notes": "LGTM from tests"}
    )
    assert resp.status_code == 200, resp.text
    
    # 4. Verify the case resumed and completed
    db_session.rollback()  # Clear transaction to see new rows
    case = db_session.query(RevenueRiskCase).filter_by(id="RR-99999").first()

    audits = db_session.query(AuditEvent).filter_by(case_id="RR-99999").order_by(AuditEvent.created_at).all()
    for a in audits:
        print(a.event_type, a.payload_json)

    assert case.status == CaseStatus.RECOVERED.value

    esc = db_session.query(Escalation).filter_by(case_id="RR-99999").first()
    assert esc.status == "APPROVED"
    assert "LGTM from tests" in esc.notes

    # Verify no double outcomes
    from app.models.outcome import RecoveryOutcome
    outcomes = db_session.query(RecoveryOutcome).filter_by(case_id="RR-99999").all()
    assert len(outcomes) == 1
    assert outcomes[0].outcome_type == "RECOVERED_FULL"
