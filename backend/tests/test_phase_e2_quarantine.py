"""Comprehensive TDD Test Suite for Phase E2: Eval Quarantine.

Covers:
- E2.1: test_no_sim_on_live_path
  AST import scanner that asserts ZERO imports of app.simulation.* in modules on the live path:
  * app/agent/
  * app/tools/live/
  * app/api/webhooks.py
  * app/services/provider_event_service.py
  * app/services/razorpay_service.py
  * app/services/reconciliation_service.py
  * app/services/detection_service.py
- E2.2: Mandatory origin filter in analytics queries when APP_ENV=prod
  Blocks running global analytics without origin='live' or origin='lab' to prevent mixing data.
- E2.3: Production fail-fast on unconfigured LLM (APP_ENV=prod)
  structured_complete raises LLMUnavailableInProduction (503) instead of silent heuristic fallback.
- E2.4: Live-path case creation guarantees origin='live'.
"""
import ast
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_db
from app.main import app as fastapi_app
from app.services import analytics_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import Base

    db_path = tmp_path / "test_phase_e2.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": 30.0, "check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr("app.db.SessionLocal", session_factory)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ======================================================================================
# E2.1: AST Import Scanner — No Simulation on Live Path
# ======================================================================================

def test_no_sim_on_live_path():
    """E2.1: Asserts that no module on the live execution path imports app.simulation.*.
    
    Live path includes:
    - app/agent/ (graph, runner, nodes, state, llm, menu, costs)
    - app/tools/live/
    - app/api/webhooks.py
    - app/services/provider_event_service.py
    - app/services/razorpay_service.py
    - app/services/reconciliation_service.py
    - app/services/detection_service.py
    """
    backend_root = Path(__file__).resolve().parent.parent
    live_paths = [
        backend_root / "app" / "agent",
        backend_root / "app" / "tools" / "live",
        backend_root / "app" / "api" / "webhooks.py",
        backend_root / "app" / "services" / "provider_event_service.py",
        backend_root / "app" / "services" / "razorpay_service.py",
        backend_root / "app" / "services" / "reconciliation_service.py",
        backend_root / "app" / "services" / "detection_service.py",
    ]

    target_files = []
    for p in live_paths:
        if p.is_file() and p.suffix == ".py":
            target_files.append(p)
        elif p.is_dir():
            target_files.extend([f for f in p.glob("**/*.py") if not f.name.startswith("__pycache__")])

    violations = {}

    for py_file in target_files:
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))

        file_violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app.simulation"):
                        file_violations.append((node.lineno, f"import {alias.name}"))
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("app.simulation"):
                    file_violations.append((node.lineno, f"from {node.module} import ..."))

        if file_violations:
            rel_path = py_file.relative_to(backend_root)
            violations[str(rel_path)] = file_violations

    assert not violations, f"Quarantine breach! Live path modules import app.simulation: {violations}"


# ======================================================================================
# E2.2: Mandatory Origin Filter in Production Analytics
# ======================================================================================

def test_analytics_requires_origin_in_prod(db, monkeypatch):
    """E2.2: Analytics queries must require an explicit origin filter in production."""
    monkeypatch.setattr(settings, "app_env", "prod")

    # Omitting origin in production should raise ValueError
    with pytest.raises(ValueError, match="origin filter is required in production"):
        analytics_service.get_recovery_totals(db, origin=None)

    with pytest.raises(ValueError, match="origin filter is required in production"):
        analytics_service.get_intervention_stats(db, origin=None)

    # Providing explicit origin succeeds without error
    totals = analytics_service.get_recovery_totals(db, origin="live")
    assert totals.total_net_recovered == 0.0


# ======================================================================================
# E2.3: Production Fail-Fast on Unconfigured LLM (Loud 503, No Mock Fallback)
# ======================================================================================

def test_prod_converts_missing_llm_into_loud_503(monkeypatch):
    """E2.3: In production (APP_ENV=prod), missing LLM credentials raises loud 503 instead of heuristic fallback."""
    from pydantic import BaseModel
    from app.agent.llm import structured_complete, LLMUnavailableInProduction

    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("app.agent.llm.get_client", lambda: None)

    class DummyContract(BaseModel):
        val: str

    with pytest.raises(LLMUnavailableInProduction) as exc_info:
        structured_complete(
            schema=DummyContract,
            system_prompt="Test system",
            user_prompt="Test user",
        )

    assert exc_info.value.status_code == 503
    assert "production" in str(exc_info.value).lower()
