"""Gateway Metric Service (Phase E2 Decoupling).

Provides access to live and recorded gateway metrics without depending on app.simulation.
"""
from typing import Dict
from sqlalchemy.orm import Session
from app.models.metric import GatewayMetric
from app.observability import traceable


@traceable(name="service.gateway_metric.load_rates", run_type="tool")
def load_gateway_rates(db: Session) -> Dict[str, float]:
    """Latest success_rate per gateway (most recent metric wins if a gateway has several)."""
    rates: Dict[str, float] = {}
    for m in db.query(GatewayMetric).order_by(GatewayMetric.recorded_at).all():
        rates[m.gateway_name] = m.success_rate
    return rates
