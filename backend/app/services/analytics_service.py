from datetime import datetime
from typing import Optional

from sqlalchemy import distinct, func
from sqlalchemy.orm import Query, Session

from app.models.case import RevenueRiskCase
from app.models.intervention import Intervention
from app.models.outcome import RecoveryOutcome
from app.schemas.analytics import RecoveryTotalsResponse, InterventionStatsResponse, InterventionStat, BaselineComparisonResponse, BaselineMetrics
from app.models.simulation import SimulationRun
from app.schemas.enums import CaseStatus
from app.observability import traceable


def _apply_case_filters(
    query: Query,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    case_type: Optional[str],
) -> Query:
    """Apply the shared case-level filters (creation window + type) to a query joined to cases."""
    if start_date:
        query = query.filter(RevenueRiskCase.created_at >= start_date)
    if end_date:
        query = query.filter(RevenueRiskCase.created_at <= end_date)
    if case_type:
        query = query.filter(RevenueRiskCase.case_type == case_type)
    return query


@traceable(name="service.analytics.get_recovery_totals", run_type="tool")
def get_recovery_totals(
    db: Session,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    case_type: Optional[str] = None,
) -> RecoveryTotalsResponse:
    # Count distinct cases, not outcome rows: a case can carry more than one outcome row, and the
    # ledger reports closed *cases*. Discounts are summed from the stored discount_total column so
    # the aggregate reconciles with net (net = gross − cost − discount) rather than being back-derived.
    query = db.query(
        func.count(distinct(RecoveryOutcome.case_id)).label("total_cases"),
        func.sum(RecoveryOutcome.gross_recovered).label("total_gross_recovered"),
        func.sum(RecoveryOutcome.cost_total).label("total_intervention_costs"),
        func.sum(RecoveryOutcome.discount_total).label("total_discounts"),
        func.sum(RecoveryOutcome.net_recovered).label("total_net_recovered"),
    ).join(RevenueRiskCase, RecoveryOutcome.case_id == RevenueRiskCase.id)

    query = _apply_case_filters(query, start_date, end_date, case_type)
    result = query.one()

    return RecoveryTotalsResponse(
        total_cases=result.total_cases or 0,
        total_gross_recovered=result.total_gross_recovered or 0.0,
        total_intervention_costs=result.total_intervention_costs or 0.0,
        total_discounts=round(result.total_discounts or 0.0, 2),
        total_net_recovered=result.total_net_recovered or 0.0,
    )


@traceable(name="service.analytics.get_intervention_stats", run_type="tool")
def get_intervention_stats(
    db: Session,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    case_type: Optional[str] = None,
) -> InterventionStatsResponse:
    query = db.query(
        Intervention.intervention_type,
        func.count(Intervention.id).label("count"),
        func.sum(Intervention.cost).label("total_cost")
    ).join(RevenueRiskCase, Intervention.case_id == RevenueRiskCase.id)

    query = _apply_case_filters(query, start_date, end_date, case_type)
    query = query.group_by(Intervention.intervention_type)

    results = query.all()

    stats = [
        InterventionStat(
            intervention_type=row.intervention_type,
            count=row.count or 0,
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
    
    # Calculate REVIVE metrics from DB
    totals = get_recovery_totals(db)
    
    total_cases = db.query(RevenueRiskCase).count()
    recovered_cases = db.query(RevenueRiskCase).filter(RevenueRiskCase.status == CaseStatus.RECOVERED.value).count()
    escalated_cases = db.query(RevenueRiskCase).filter(RevenueRiskCase.status == CaseStatus.ESCALATED.value).count()
    
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
