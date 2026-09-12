from collections import Counter
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy import distinct, func
from sqlalchemy.orm import Query, Session

from app.models.case import RevenueRiskCase
from app.models.intervention import Intervention
from app.models.outcome import RecoveryOutcome
from app.models.simulation import SimulationRun
from app.schemas.analytics import (
    BaselineComparisonResponse,
    BaselineMetrics,
    InterventionStat,
    InterventionStatsResponse,
    RecoveryTotalsResponse,
)
from app.schemas.enums import CaseStatus, OutcomeType
from app.observability import traceable


def _apply_case_filters(
    query: Query,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    case_type: Optional[str],
    origin: Optional[str] = None,
) -> Query:
    """Apply the shared case-level filters (creation window, type, and origin) to a query joined to cases."""
    if start_date:
        query = query.filter(RevenueRiskCase.created_at >= start_date)
    if end_date:
        query = query.filter(RevenueRiskCase.created_at <= end_date)
    if case_type:
        query = query.filter(RevenueRiskCase.case_type == case_type)
    if origin:
        query = query.filter(RevenueRiskCase.origin == origin)
    return query


def _is_later_outcome(a: RecoveryOutcome, b: RecoveryOutcome) -> bool:
    """True when outcome ``a`` strictly supersedes ``b`` (created_at, then id as a tie-break)."""
    return (a.created_at, a.id) > (b.created_at, b.id)


def _case_level_metrics(
    db: Session,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    case_type: Optional[str],
    origin: Optional[str] = None,
) -> tuple:
    """Case-level aggregates (amount at risk, recovery rate, mean recovery time).

    A case can carry more than one outcome row (e.g. an escalate→resume path that closes twice), so
    each case contributes its *latest* outcome here; the money ledger below still sums outcome rows.
    """
    case_rows = _apply_case_filters(
        db.query(RevenueRiskCase, RecoveryOutcome).join(
            RecoveryOutcome, RecoveryOutcome.case_id == RevenueRiskCase.id
        ),
        start_date,
        end_date,
        case_type,
        origin,
    ).all()

    latest: Dict[str, tuple] = {}
    for case, outcome in case_rows:
        previous = latest.get(case.id)
        if previous is None or _is_later_outcome(outcome, previous[1]):
            latest[case.id] = (case, outcome)

    amount_at_risk = 0.0
    recovered_count = 0
    recovery_hours = []
    for case, outcome in latest.values():
        amount_at_risk += case.amount_at_risk or 0.0
        if outcome.outcome_type == OutcomeType.RECOVERED_FULL.value:
            recovered_count += 1
            closed_at = outcome.verified_at or outcome.created_at
            if case.created_at and closed_at:
                c_at = case.created_at if case.created_at.tzinfo is not None else case.created_at.replace(tzinfo=timezone.utc)
                cl_at = closed_at if closed_at.tzinfo is not None else closed_at.replace(tzinfo=timezone.utc)
                recovery_hours.append((cl_at - c_at).total_seconds() / 3600.0)

    total_cases = len(latest)
    avg_hours = sum(recovery_hours) / len(recovery_hours) if recovery_hours else None
    return total_cases, amount_at_risk, recovered_count, avg_hours


@traceable(name="service.analytics.get_recovery_totals", run_type="tool")
def get_recovery_totals(
    db: Session,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    case_type: Optional[str] = None,
    origin: Optional[str] = None,
) -> RecoveryTotalsResponse:
    # Money ledger: sums over outcome rows (kept as-is so the aggregate reconciles with the stored
    # net per outcome; net = gross − cost − discount) joined to their cases for the filters.
    query = db.query(
        func.count(distinct(RecoveryOutcome.case_id)).label("total_cases"),
        func.sum(RecoveryOutcome.gross_recovered).label("total_gross_recovered"),
        func.sum(RecoveryOutcome.cost_total).label("total_intervention_costs"),
        func.sum(RecoveryOutcome.discount_total).label("total_discounts"),
        func.sum(RecoveryOutcome.net_recovered).label("total_net_recovered"),
    ).join(RevenueRiskCase, RecoveryOutcome.case_id == RevenueRiskCase.id)

    query = _apply_case_filters(query, start_date, end_date, case_type, origin)
    result = query.one()

    total_cases, amount_at_risk, recovered_count, avg_hours = _case_level_metrics(
        db, start_date, end_date, case_type, origin
    )
    recovery_rate = recovered_count / max(total_cases, 1)

    return RecoveryTotalsResponse(
        total_cases=result.total_cases or 0,
        total_amount_at_risk=round(amount_at_risk, 2),
        total_gross_recovered=result.total_gross_recovered or 0.0,
        total_intervention_costs=result.total_intervention_costs or 0.0,
        total_discounts=round(result.total_discounts or 0.0, 2),
        total_net_recovered=result.total_net_recovered or 0.0,
        recovery_rate=round(recovery_rate, 4),
        average_recovery_time_hours=round(avg_hours, 2) if avg_hours is not None else None,
    )


@traceable(name="service.analytics.get_intervention_stats", run_type="tool")
def get_intervention_stats(
    db: Session,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    case_type: Optional[str] = None,
    origin: Optional[str] = None,
) -> InterventionStatsResponse:
    query = db.query(
        Intervention.intervention_type,
        func.count(Intervention.id).label("count"),
        func.sum(Intervention.cost).label("total_cost")
    ).join(RevenueRiskCase, Intervention.case_id == RevenueRiskCase.id)

    query = _apply_case_filters(query, start_date, end_date, case_type, origin)
    query = query.group_by(Intervention.intervention_type)

    results = query.all()

    # Per-type success counts, derived from the stored outcome payload (a successful intervention
    # records ``success: true`` in its payload_json). Loaded in Python — the set is small and this
    # stays portable across SQLite's JSON support.
    success_rows = _apply_case_filters(
        db.query(Intervention).join(RevenueRiskCase, Intervention.case_id == RevenueRiskCase.id),
        start_date,
        end_date,
        case_type,
        origin,
    ).all()
    success_by_type: Counter = Counter()
    for intervention in success_rows:
        if (intervention.payload_json or {}).get("success") is True:
            success_by_type[intervention.intervention_type] += 1

    stats = [
        InterventionStat(
            intervention_type=row.intervention_type,
            count=row.count or 0,
            success_count=success_by_type.get(row.intervention_type, 0),
            total_cost=row.total_cost or 0.0,
        )
        for row in results
    ]

    return InterventionStatsResponse(stats=stats)

@traceable(name="service.analytics.get_baseline_comparison", run_type="tool")
def get_baseline_comparison(db: Session, seed: Optional[int] = None) -> BaselineComparisonResponse:
    # Find simulation run
    query = db.query(SimulationRun)
    if seed is not None:
        query = query.filter(SimulationRun.seed == seed)
    
    sim_run = query.order_by(SimulationRun.created_at.desc()).first()
    
    if not sim_run or not sim_run.metrics_json or "baseline" not in sim_run.metrics_json:
        # Return empty if no run exists
        return BaselineComparisonResponse(
            simulation_run_id="none",
            seed=0,
            baseline=BaselineMetrics(),
            revive=BaselineMetrics(),
            delta_net=0.0,
            delta_escalation_rate=0.0
        )
        
    baseline_data = sim_run.metrics_json["baseline"]
    baseline_metrics = BaselineMetrics(
        gross_recovered=baseline_data.get("gross_recovered", 0.0),
        net_recovered=baseline_data.get("net_recovered", 0.0),
        recovery_rate=baseline_data.get("recovery_rate", 0.0),
        escalation_rate=baseline_data.get("escalation_rate", 0.0)
    )
    
    # Calculate REVIVE metrics strictly from lab cases (benchmark isolation)
    totals = get_recovery_totals(db, origin="lab")
    
    total_cases = db.query(RevenueRiskCase).filter(RevenueRiskCase.origin == "lab").count()
    recovered_cases = db.query(RevenueRiskCase).filter(
        RevenueRiskCase.origin == "lab",
        RevenueRiskCase.status == CaseStatus.RECOVERED.value
    ).count()
    escalated_cases = db.query(RevenueRiskCase).filter(
        RevenueRiskCase.origin == "lab",
        RevenueRiskCase.status == CaseStatus.ESCALATED.value
    ).count()
    
    revive_recovery_rate = recovered_cases / max(total_cases, 1)
    revive_escalation_rate = escalated_cases / max(total_cases, 1)
    
    revive_metrics = BaselineMetrics(
        gross_recovered=totals.total_gross_recovered,
        net_recovered=totals.total_net_recovered,
        recovery_rate=round(revive_recovery_rate, 4),
        escalation_rate=round(revive_escalation_rate, 4)
    )
    
    delta_net = revive_metrics.net_recovered - baseline_metrics.net_recovered
    delta_escalation_rate = revive_metrics.escalation_rate - baseline_metrics.escalation_rate
    
    return BaselineComparisonResponse(
        simulation_run_id=sim_run.id,
        seed=sim_run.seed,
        baseline=baseline_metrics,
        revive=revive_metrics,
        delta_net=round(delta_net, 2),
        delta_escalation_rate=round(delta_escalation_rate, 4)
    )
