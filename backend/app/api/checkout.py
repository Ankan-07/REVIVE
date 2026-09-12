"""Razorpay Standard Checkout API (real-payment verification for failed payments).

Endpoints:
* ``POST /razorpay/create-order``   — create a REAL Razorpay order for a FAILED payment.
* ``POST /razorpay/verify-payment`` — verify the checkout signature; on success settle the
  payment and close the case through the deterministic ledger.

Test-mode by design: the repo ships ``rzp_test_*`` keys, so no real money moves. When the
Razorpay keys are absent from the environment these return ``503`` and the engine stays
fully simulated (tests run hermetic with the keys unset).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.db import get_db
from app.schemas.checkout import (
    CreateOrderRequest,
    CreateOrderResponse,
    VerifyPaymentRequest,
    VerifyPaymentResponse,
)
from app.services import razorpay_service

router = APIRouter(prefix="/razorpay", tags=["Razorpay"])


def _http(error: razorpay_service.RazorpayServiceError) -> HTTPException:
    """Map typed service errors to HTTP responses."""
    return HTTPException(status_code=error.status_code, detail=error.detail)


@router.post("/create-order", response_model=CreateOrderResponse)
def create_order(
    body: CreateOrderRequest,
    auth=Depends(require_api_key("operator")),
    db: Session = Depends(get_db),
):
    """Validate a FAILED payment and create a real Razorpay order for its amount."""
    try:
        result = razorpay_service.create_order_for_payment(db, payment_id=body.payment_id)
    except razorpay_service.RazorpayServiceError as exc:
        raise _http(exc)
    return result


@router.post("/verify-payment", response_model=VerifyPaymentResponse)
def verify_payment(body: VerifyPaymentRequest, db: Session = Depends(get_db)):
    """Verify the checkout signature; on match, mark the payment paid and close its case."""
    try:
        result = razorpay_service.verify_and_settle(
            db,
            payment_id=body.payment_id,
            order_id=body.razorpay_order_id,
            razorpay_payment_id=body.razorpay_payment_id,
            razorpay_signature=body.razorpay_signature,
        )
    except razorpay_service.RazorpayServiceError as exc:
        raise _http(exc)
    return result
