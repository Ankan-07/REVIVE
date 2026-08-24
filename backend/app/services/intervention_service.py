"""Intervention persistence with idempotency (PRD §38).

The action tools go through this service so that replaying the same ``case_id:action:attempt`` key
returns the existing row instead of executing a second time. Interventions have no dedicated
idempotency-key column, so the key is stored inside ``payload_json`` and matched in Python — there
are only a handful of interventions per case, so a scan is cheap and fully portable across SQLite.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.domain.ids import generate_id
from app.models.intervention import Intervention
from app.observability import traceable

_EXECUTED = "EXECUTED"


@traceable(name="service.intervention.get_by_idempotency_key", run_type="tool")
def get_by_idempotency_key(db: Session, case_id: str, key: str) -> Optional[Intervention]:
    """Return the intervention previously written under ``key`` for this case, if any."""
    rows = db.query(Intervention).filter(Intervention.case_id == case_id).all()
    for row in rows:
        if (row.payload_json or {}).get("idempotency_key") == key:
            return row
    return None


@traceable(name="service.intervention.create_executed", run_type="tool")
def create_executed(
    db: Session,
    *,
    case_id: str,
    action: str,
    cost: float,
    idempotency_key: str,
    result: Dict[str, Any],
    discount_amount: float = 0.0,
) -> Intervention:
    """Persist a freshly executed intervention and return the committed row."""
    intervention = Intervention(
        id=generate_id("INT", db),
        case_id=case_id,
        intervention_type=action,
        cost=cost,
        discount_amount=discount_amount,
        status=_EXECUTED,
        payload_json={"idempotency_key": idempotency_key, **result},
        executed_at=datetime.utcnow(),
    )
    db.add(intervention)
    db.commit()
    db.refresh(intervention)
    return intervention


@traceable(name="service.intervention.totals", run_type="tool")
def totals(db: Session, case_id: str) -> Dict[str, float]:
    """Sum cost and discount across every intervention executed for a case (realized-net ledger)."""
    rows = db.query(Intervention).filter(Intervention.case_id == case_id).all()
    return {
        "cost_total": float(sum(r.cost or 0.0 for r in rows)),
        "discount_total": float(sum(r.discount_amount or 0.0 for r in rows)),
    }
