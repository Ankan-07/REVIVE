import json
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
import app.models  # noqa: F401
from app.models.simulation import SimulationRun
from app.simulation.generator import run_simulation


def generate_baseline():
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
        if not sim_run:
            raise RuntimeError("SimulationRun row not found after run_simulation")

        baseline_contract = {
            "seed": 42,
            "generator_result": res,
            "metrics_json": sim_run.metrics_json,
        }

        fixtures_dir = Path("tests") / "fixtures"
        fixtures_dir.mkdir(parents=True, exist_ok=True)
        fixture_path = fixtures_dir / "eval_baseline_seed42.json"

        fixture_path.write_text(json.dumps(baseline_contract, indent=2), encoding="utf-8")
        print(f"Eval baseline saved to {fixture_path}")
        print("Summary of baseline metrics:")
        print(json.dumps(sim_run.metrics_json.get("baseline", {}), indent=2))
        return baseline_contract
    finally:
        session.close()


if __name__ == "__main__":
    generate_baseline()
