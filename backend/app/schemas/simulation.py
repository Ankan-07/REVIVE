from pydantic import BaseModel
from typing import Optional, Dict, List

from app.config import settings


class SimulationRequest(BaseModel):
    seed: int = settings.simulation_seed  # wires the previously-dead config default
    customer_count: int = 50
    payment_count: int = 100
    order_count: Optional[int] = None  # None -> generator scales from customer_count
    checkout_count: int = 30
    invoice_count: int = 30
    emit_events: bool = False  # if True, run the detector after seeding so failures become cases


class GatewaySnapshot(BaseModel):
    gateway: str
    success_rate: float
    baseline_success_rate: Optional[float] = None
    health_status: str


class SimulationResponse(BaseModel):
    status: str
    seed: int
    simulation_run_id: Optional[str] = None
    customers_created: int
    orders_created: int = 0
    payments_created: int
    checkouts_created: int = 0
    invoices_created: int = 0
    cases_created: int
    failed_by_reason: Optional[Dict[str, int]] = None
    gateways: Optional[List[GatewaySnapshot]] = None
    amount_at_risk: Optional[float] = None
    ground_truth: Optional[Dict[str, int]] = None
    metrics: Optional[Dict[str, int]] = None  # back-compat: {"failed_payments": N}


class PaymentSimRequest(BaseModel):
    action: str  # InterventionType value: RETRY_PAYMENT | SWITCH_GATEWAY | CREATE_PAYMENT_LINK
    attempt: int = 1


class PaymentSimResult(BaseModel):
    payment_id: str
    action: str
    attempt: int
    success: bool
    probability: float
    gateway_used: str
    recovery_roll: float
    signals: Dict[str, float]  # customer_intent, gateway_health, method_health
