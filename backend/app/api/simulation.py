import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.config import settings
from app.db import get_db
from app.schemas.simulation import (
    SimulationRequest,
    SimulationResponse,
    PaymentSimRequest,
    PaymentSimResult,
)
from app.simulation.generator import run_simulation
from app.simulation.payment_sim import simulate_payment, PaymentNotFoundError
from app.services.detector import emit_failed_payment_events


router = APIRouter(prefix="/simulation", tags=["Simulation"])


@router.post("/run", response_model=SimulationResponse)
def trigger_simulation(request: SimulationRequest, db: Session = Depends(get_db)):
    result = run_simulation(
        db=db,
        seed=request.seed,
        customer_count=request.customer_count,
        payment_count=request.payment_count,
        order_count=request.order_count,
    )

    # Optionally close the Phase 2->3 seam in one call: turn the seeded failures into cases by
    # POSTing PAYMENT_FAILED events to the real /events/ endpoint (needs the server running).
    if request.emit_events:
        with httpx.Client(base_url=settings.internal_api_base_url, timeout=30.0) as client:
            summary = emit_failed_payment_events(db, client)
        result["cases_created"] = summary["cases_created"]

    return SimulationResponse(**result)


@router.post("/payments/{payment_id}/simulate", response_model=PaymentSimResult)
def simulate_payment_action(
    payment_id: str, request: PaymentSimRequest, db: Session = Depends(get_db)
):
    """Deterministic, read-only payment-recovery oracle (PRD §28).

    Resolves what `action` would do to a failed payment without mutating anything. Idempotent:
    repeated calls with the same (payment, action) return the same outcome.
    """
    try:
        result = simulate_payment(
            db=db, payment_id=payment_id, action=request.action, attempt=request.attempt
        )
    except PaymentNotFoundError:
        raise HTTPException(status_code=404, detail=f"Payment {payment_id} not found")
    return PaymentSimResult(**result)
