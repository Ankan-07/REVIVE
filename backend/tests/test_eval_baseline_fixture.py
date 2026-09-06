import json
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
import app.models  # noqa: F401
from app.models.simulation import SimulationRun
from app.simulation.generator import run_simulation


def test_eval_baseline_seed42_matches_fixture():
    """Phase 0.4 freeze check: seeded sim (seed 42) + baseline matches eval_baseline_seed42.json.
    
    This regression anchor guarantees that future simulation refactoring (Phase E eval lab)
    never silently drifts baseline recovery rate or ground truth generation.
    """
    fixture_path = Path(__file__).parent / "fixtures" / "eval_baseline_seed42.json"
    assert fixture_path.exists(), f"Missing fixture file at {fixture_path}"

    with open(fixture_path, "r", encoding="utf-8") as f:
        expected = json.load(f)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    try:
        res = run_simulation(
            session,
            seed=42,
            customer_count=50,
            payment_count=100,
            checkout_count=30,
            invoice_count=30,
        )

        sim_run = session.query(SimulationRun).filter(SimulationRun.seed == 42).first()
        assert sim_run is not None

        # Compare generator summary
        assert res == expected["generator_result"]

        # Compare metrics and baseline
        assert sim_run.metrics_json == expected["metrics_json"]

        # Specifically verify baseline metrics anchor values
        baseline = sim_run.metrics_json["baseline"]
        assert baseline["strategy"] == "BASELINE"
        assert baseline["cases_processed"] == 14
        assert baseline["recovered_count"] == 4
        assert baseline["gross_recovered"] == 5850.81
        assert baseline["cost_total"] == 80.0
        assert baseline["recovery_rate"] == 0.2857
    finally:
        session.close()
