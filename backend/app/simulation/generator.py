"""Seeded revenue simulator (PRD §26-28).

Bulk-generates a reproducible dataset: customers, orders, payments (with a calibrated leak mix),
and gateway health metrics (one gateway deliberately degraded). Every value derives from a single
isolated `random.Random(seed)` stream and IDs/timestamps are deterministic, so the same seed
reproduces byte-identical data.

Note: this is a bulk seeder and writes ORM objects directly rather than going through the service
layer (a deliberate exception -- per-row service calls returning Pydantic models are the wrong tool
for bulk generation). The payment-outcome math lives in `payment_sim` and is reused here for the
ground-truth projections.
"""
import random
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models.customer import Customer
from app.models.order import Order
from app.models.payment import Payment
from app.models.metric import GatewayMetric
from app.models.simulation import SimulationRun
from app.schemas.enums import PaymentStatus, InterventionType
from app.simulation.payment_sim import recovery_probability, gateway_health_for, clamp01

# Fixed reference point so generated timestamps are deterministic (never wall-clock).
SIM_EPOCH = datetime(2026, 1, 1)

GATEWAYS = ["STRIPE", "RAZORPAY", "PAYU"]

# Calibrated failure mix (PRD §26): cumulative thresholds over a single uniform draw.
P_INSUFFICIENT_FUNDS = 0.05          # f < 0.05
P_TIMEOUT = 0.08                     # 0.05 <= f < 0.08  (3%)
P_EXPIRED_CARD = 0.10                # 0.08 <= f < 0.10  (2%)  ; f >= 0.10 -> succeeded

SEGMENTS = ["STANDARD", "PREMIUM", "VIP"]
SEGMENT_INTENT_BONUS = {"STANDARD": 0.0, "PREMIUM": 0.05, "VIP": 0.10}


def run_simulation(
    db: Session,
    seed: Optional[int] = None,
    customer_count: int = 50,
    payment_count: int = 100,
    order_count: Optional[int] = None,
) -> Dict[str, Any]:
    seed = settings.simulation_seed if seed is None else seed
    if order_count is None:
        order_count = customer_count * 2

    rng = random.Random(seed)  # isolated stream -- no global state leakage across tests/requests

    # Deterministic sequential IDs matching the canonical PREFIX-00001 format.
    counters: Dict[str, int] = {}

    def sid(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{prefix}-{counters[prefix]:05d}"

    # --- Gateway health: pick one gateway to be degraded (drives the switch_gateway demo) ---
    degraded_gateway = rng.choice(GATEWAYS)
    gateway_rates: Dict[str, float] = {}
    gateway_snapshot: List[Dict[str, Any]] = []
    for name in GATEWAYS:
        if name == degraded_gateway:
            success_rate = round(rng.uniform(0.65, 0.75), 4)
            baseline = round(rng.uniform(0.96, 0.98), 4)
            latency = round(rng.uniform(800.0, 1500.0), 1)
            health_status = "DEGRADED"
        else:
            success_rate = round(rng.uniform(0.95, 0.98), 4)
            baseline = round(rng.uniform(0.96, 0.98), 4)
            latency = round(rng.uniform(80.0, 250.0), 1)
            health_status = "HEALTHY"
        gateway_rates[name] = success_rate
        gateway_snapshot.append(
            {
                "gateway": name,
                "success_rate": success_rate,
                "baseline_success_rate": baseline,
                "health_status": health_status,
            }
        )
        db.add(
            GatewayMetric(
                id=sid("GWM"),
                gateway_name=name,
                success_rate=success_rate,
                baseline_success_rate=baseline,
                latency_ms=latency,
                health_status=health_status,
                recorded_at=SIM_EPOCH,
            )
        )
    db.commit()

    # --- Customers ---
    customers: List[Customer] = []
    for i in range(customer_count):
        segment = rng.choice(SEGMENTS)
        intent = clamp01(rng.uniform(0.40, 0.95) + SEGMENT_INTENT_BONUS[segment])
        cust = Customer(
            id=sid("CUS"),
            name=f"Sim Customer {i}",
            email=f"sim_{i}@example.com",
            phone=f"+919876543{i:03d}",
            segment=segment,
            ltv_amount=round(rng.uniform(100.0, 10000.0), 2),
            risk_score=round(rng.uniform(0.0, 1.0), 2),
            intent_score=round(intent, 4),
            created_at=SIM_EPOCH + timedelta(days=rng.randint(0, 365)),
        )
        customers.append(cust)
        db.add(cust)
    db.commit()

    # --- Orders (linked to customers) ---
    orders_by_customer: Dict[str, List[str]] = {c.id: [] for c in customers}
    for _ in range(order_count):
        cust = rng.choice(customers)
        order_id = sid("ORD")
        db.add(
            Order(
                id=order_id,
                customer_id=cust.id,
                amount=round(rng.uniform(50.0, 5000.0), 2),
                currency="INR",
                status=rng.choices(
                    ["COMPLETED", "PENDING", "CANCELLED"], weights=[0.8, 0.15, 0.05]
                )[0],
                items_json={"item_count": rng.randint(1, 5)},
                created_at=SIM_EPOCH + timedelta(days=rng.randint(0, 200)),
            )
        )
        orders_by_customer[cust.id].append(order_id)
    db.commit()

    # --- Payments (calibrated failure mix + §28 signals) ---
    customer_intent: Dict[str, float] = {c.id: c.intent_score for c in customers}
    payments: List[Payment] = []
    for _ in range(payment_count):
        cust = rng.choice(customers)

        # Link to one of the customer's orders most of the time.
        cust_orders = orders_by_customer.get(cust.id, [])
        order_id = rng.choice(cust_orders) if (cust_orders and rng.random() < 0.7) else None

        f = rng.random()
        if f < P_INSUFFICIENT_FUNDS:
            status, error_code = PaymentStatus.FAILED.value, "insufficient_funds"
            gateway = rng.choice(GATEWAYS)
            method_health = round(rng.uniform(0.20, 0.50), 4)
        elif f < P_TIMEOUT:
            status, error_code = PaymentStatus.FAILED.value, "timeout"
            gateway = degraded_gateway  # timeouts concentrate on the degraded gateway
            method_health = round(rng.uniform(0.85, 0.98), 4)
        elif f < P_EXPIRED_CARD:
            status, error_code = PaymentStatus.FAILED.value, "expired_card"
            gateway = rng.choice(GATEWAYS)
            method_health = round(rng.uniform(0.00, 0.10), 4)
        else:
            status, error_code = PaymentStatus.SUCCEEDED.value, None
            gateway = rng.choice(GATEWAYS)
            method_health = round(rng.uniform(0.85, 1.00), 4)

        error_message = None if error_code is None else f"Payment failed due to {error_code}"

        payment = Payment(
            id=sid("PAY"),
            customer_id=cust.id,
            order_id=order_id,
            amount=round(rng.uniform(50.0, 2000.0), 2),
            currency="INR",
            gateway=gateway,
            status=status,
            error_code=error_code,
            error_message=error_message,
            attempt_count=1,
            method_health=method_health,
            recovery_roll=round(rng.random(), 6),
            created_at=SIM_EPOCH + timedelta(days=rng.randint(0, 120), seconds=rng.randint(0, 86399)),
        )
        payments.append(payment)
        db.add(payment)
    db.commit()

    # --- Ground-truth projections over the failed payments (via the shared engine math) ---
    failed = [p for p in payments if p.status == PaymentStatus.FAILED.value]
    failed_by_reason: Dict[str, int] = {"insufficient_funds": 0, "timeout": 0, "expired_card": 0}
    gt = {"failed": len(failed), "recoverable_by_retry": 0, "recoverable_by_switch": 0,
          "recoverable_by_link": 0, "unrecoverable": 0}
    amount_at_risk = 0.0

    for p in failed:
        if p.error_code in failed_by_reason:
            failed_by_reason[p.error_code] += 1
        amount_at_risk += p.amount

        intent = customer_intent.get(p.customer_id, 0.0)
        retry_h, _ = gateway_health_for(gateway_rates, p.gateway, InterventionType.RETRY_PAYMENT.value)
        switch_h, _ = gateway_health_for(gateway_rates, p.gateway, InterventionType.SWITCH_GATEWAY.value)
        link_h, _ = gateway_health_for(gateway_rates, p.gateway, InterventionType.CREATE_PAYMENT_LINK.value)

        rec_retry = p.recovery_roll < recovery_probability(intent, retry_h, p.method_health)
        rec_switch = p.recovery_roll < recovery_probability(intent, switch_h, p.method_health)
        rec_link = p.recovery_roll < recovery_probability(intent, link_h, 1.0)  # link resets method

        gt["recoverable_by_retry"] += int(rec_retry)
        gt["recoverable_by_switch"] += int(rec_switch)
        gt["recoverable_by_link"] += int(rec_link)
        if not (rec_retry or rec_switch or rec_link):
            gt["unrecoverable"] += 1

    metrics_json = {
        "totals": {
            "customers": customer_count,
            "orders": order_count,
            "payments": payment_count,
            "succeeded": payment_count - len(failed),
            "failed": len(failed),
        },
        "failed_by_reason": failed_by_reason,
        "gateways": gateway_snapshot,
        "amount_at_risk": round(amount_at_risk, 2),
        "ground_truth": gt,
    }

    sim_run = SimulationRun(
        id=sid("SIM"),
        seed=seed,
        name=f"Run_seed_{seed}",
        config_json={
            "seed": seed,
            "customer_count": customer_count,
            "order_count": order_count,
            "payment_count": payment_count,
            "degraded_gateway": degraded_gateway,
        },
        metrics_json=metrics_json,
        status="COMPLETED",
        created_at=SIM_EPOCH,
    )
    db.add(sim_run)
    db.commit()

    return {
        "status": "success",
        "seed": seed,
        "simulation_run_id": sim_run.id,
        "customers_created": customer_count,
        "orders_created": order_count,
        "payments_created": payment_count,
        "cases_created": 0,  # cases are created by the Phase 3 event handler
        "failed_by_reason": failed_by_reason,
        "gateways": gateway_snapshot,
        "amount_at_risk": round(amount_at_risk, 2),
        "ground_truth": gt,
        "metrics": {"failed_payments": len(failed)},
    }
