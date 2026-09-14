"""Recovery-outcome ledger (PRD §23, §47, §57).

Records the *verified* economic result of a case as a :class:`RecoveryOutcome` row. Net recovery is
computed deterministically here — ``net = gross_recovered − cost_total − discount_total`` — so the
ledger and the benchmark (Phase 8) read a single, trustworthy number per case (§47: optimize and
report expected/realized NET, never gross).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.domain.ids import generate_id
from app.models.outcome import RecoveryOutcome
from app.observability import traceable


@traceable(name="service.outcome.record", run_type="tool")
def record_outcome(
    db: Session,
    *,
    case_id: str,
    outcome_type: str,
    gross_recovered: float,
    cost_total: float,
    discount_total: float = 0.0,
    gateway_fee_paise: int = 0,
    verified: bool = True,
) -> RecoveryOutcome:
    """Persist and return the recovery outcome, computing net from the parts."""
    gateway_fee = float(gateway_fee_paise) / 100.0
    net = gross_recovered - cost_total - discount_total - gateway_fee
    outcome = RecoveryOutcome(
        id=generate_id("OUT", db),
        case_id=case_id,
        outcome_type=outcome_type,
        gross_recovered=gross_recovered,
        net_recovered=net,
        cost_total=cost_total,
        discount_total=discount_total,
        gateway_fee_paise=gateway_fee_paise,
        verified_at=datetime.now(timezone.utc) if verified else None,
    )
    db.add(outcome)
    db.commit()
    db.refresh(outcome)
    return outcome
