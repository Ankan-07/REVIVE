from typing import List, Optional
from pydantic import BaseModel, Field

class RecoveryTotalsResponse(BaseModel):
    total_cases: int = Field(default=0, description="Total number of closed cases")
    total_amount_at_risk: float = Field(default=0.0, description="Total amount at risk across the closed cases")
    total_gross_recovered: float = Field(default=0.0, description="Total gross revenue recovered")
    total_intervention_costs: float = Field(default=0.0, description="Total cost of all interventions")
    total_discounts: float = Field(default=0.0, description="Total amount of discounts offered")
    total_net_recovered: float = Field(default=0.0, description="Total net revenue recovered")
    recovery_rate: float = Field(default=0.0, description="Share of closed cases that recovered (0-1)")
    average_recovery_time_hours: Optional[float] = Field(default=None, description="Mean hours from case creation to verified recovery")

class InterventionStat(BaseModel):
    intervention_type: str = Field(description="The type of intervention")
    count: int = Field(default=0, description="Number of times this intervention was executed")
    success_count: int = Field(default=0, description="Number of executed interventions that reported success")
    total_cost: float = Field(default=0.0, description="Total cost for this intervention type")

class InterventionStatsResponse(BaseModel):
    stats: List[InterventionStat] = Field(default_factory=list, description="Statistics grouped by intervention type")

class BaselineMetrics(BaseModel):
    gross_recovered: float = Field(default=0.0)
    net_recovered: float = Field(default=0.0)
    recovery_rate: float = Field(default=0.0)
    escalation_rate: float = Field(default=0.0)

class BaselineComparisonResponse(BaseModel):
    simulation_run_id: str
    seed: int
    baseline: BaselineMetrics = Field(description="Metrics for naive baseline strategy")
    revive: BaselineMetrics = Field(description="Metrics for REVIVE agent strategy")
    delta_net: float = Field(description="Difference in net revenue (REVIVE - Baseline)")
    delta_escalation_rate: float = Field(description="Difference in escalation rate (REVIVE - Baseline)")
