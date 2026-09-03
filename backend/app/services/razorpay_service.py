"""Razorpay Standard Checkout integration (PRD §40 — real-payment verification).

Turns a *simulated* payment story into a real one, end to end, without touching the
agent's deterministic core:

1. ``create_order_for_payment``  — validate the failed payment, then create a REAL
   Razorpay order (``POST /v1/orders`` via the official SDK) for its amount.
2. ``verify_and_settle``          — the customer pays in the checkout modal (test card in
   test mode); the frontend returns ``(order_id, payment_id, signature)`` and this
   verifies the HMAC-SHA256 signature exactly as Razorpay documents, then settles the
   payment through the existing deterministic service layer (payment row -> SUCCEEDED,
   case -> RECOVERED, net ledger written + audited).

Why HMAC locally instead of ``client.utility.verify_payment_signature``: the algorithm is
two lines of stdlib and makes the verification path fully testable offline (no SDK call,
no network). It is the same check the SDK performs.

Keys are read from the environment at call time (never hardcoded). With no
``RAZORPAY_KEY_ID``/``RAZORPAY_KEY_SECRET`` set the endpoints fail with a clear 503 and
the rest of the engine stays fully simulated — same convention as the LLM client.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional

from sqlalchemy.orm import Session

from app.audit import recorder
from app.models.case import RevenueRiskCase
from app.models.payment import Payment
from app.schemas.enums import CaseStatus, OutcomeType, PaymentStatus
from app.services import case_service, intervention_service, outcome_service
from app.observability import traceable

MIN_AMOUNT_INR = 1.0  # Razorpay minimum order amount is 100 paise (₹1)
_CURRENCY = "INR"
_CLOSED_STATUSES = {
    CaseStatus.RECOVERED.value,
    CaseStatus.CLOSED_NO_RECOVERY.value,
    CaseStatus.EXPIRED.value,
}


# --------------------------------------------------------------------------------------
# Typed errors -> HTTP mapping in the API layer
# --------------------------------------------------------------------------------------
class RazorpayServiceError(RuntimeError):
    status_code = 500

    def __init__(self, detail: str, status_code: int | None = None):
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code


class NotConfiguredError(RazorpayServiceError):
    def __init__(self):
        super().__init__(
            "Razorpay is not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env.",
            status_code=503,
        )


class PaymentNotFoundError(RazorpayServiceError):
    def __init__(self, payment_id: str):
        super().__init__(f"Payment {payment_id} not found", status_code=404)


class InvalidStateError(RazorpayServiceError):
    pass


class InvalidSignatureError(RazorpayServiceError):
    def __init__(self):
        super().__init__("Signature verification failed — payment was NOT marked as paid.", status_code=400)


class GatewayError(RazorpayServiceError):
    def __init__(self, detail: str):
        super().__init__(f"Razorpay API error: {detail}", status_code=502)


# --------------------------------------------------------------------------------------
# Config + gateway boundary (monkeypatchable in tests)
# --------------------------------------------------------------------------------------
def is_configured() -> bool:
    return bool(os.getenv("RAZORPAY_KEY_ID") and os.getenv("RAZORPAY_KEY_SECRET"))


def _key_secret() -> Optional[str]:
    return os.getenv("RAZORPAY_KEY_SECRET")


def _razorpay_client():
    """Lazily built official SDK client. Callers must have checked :func:`is_configured`."""
    import razorpay

    return razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")))


def _create_order_on_gateway(amount_paise: int, receipt: str, notes: dict) -> dict:
    """Boundary around ``POST /v1/orders`` so tests never hit the network."""
    return _razorpay_client().order.create(
        {
            "amount": amount_paise,
            "currency": _CURRENCY,
            "receipt": receipt,
            "notes": notes,
        }
    )


def _signature_is_valid(order_id: str, razorpay_payment_id: str, signature: str) -> bool:
    """HMAC-SHA256(order_id + '|' + payment_id, key_secret) — the Razorpay doc algorithm."""
    secret = _key_secret()
    if not secret:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{order_id}|{razorpay_payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _open_case_for_payment(db: Session, payment_id: str) -> Optional[RevenueRiskCase]:
    """The case working this payment that is not already closed/recovered."""
    return (
        db.query(RevenueRiskCase)
        .filter(RevenueRiskCase.payment_id == payment_id)
        .filter(RevenueRiskCase.status.notin_(_CLOSED_STATUSES))
        .order_by(RevenueRiskCase.created_at.asc())
        .first()
    )


# --------------------------------------------------------------------------------------
# 1. Create a real Razorpay order for a failed payment
# --------------------------------------------------------------------------------------
@traceable(name="service.razorpay.create_order_for_payment", run_type="tool")
def create_order_for_payment(db: Session, *, payment_id: str) -> dict:
    if not is_configured():
        raise NotConfiguredError()

    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment is None:
        raise PaymentNotFoundError(payment_id)
    if payment.status == PaymentStatus.SUCCEEDED.value:
        raise InvalidStateError(
            f"Payment {payment_id} is already SUCCEEDED — nothing to collect.",
            status_code=409,
        )
    if payment.status != PaymentStatus.FAILED.value:
        raise InvalidStateError(
            f"Payment {payment_id} is not in a recoverable (FAILED) state.",
            status_code=409,
        )

    amount_inr = float(payment.amount)
    if amount_inr < MIN_AMOUNT_INR:
        raise InvalidStateError(
            f"Amount ₹{amount_inr} is below Razorpay's ₹{MIN_AMOUNT_INR} minimum.",
            status_code=400,
        )

    amount_paise = int(round(amount_inr * 100))
    case = _open_case_for_payment(db, payment_id)

    try:
        order = _create_order_on_gateway(
            amount_paise=amount_paise,
            receipt=payment.id,  # PAY-XXXXX, well under Razorpay's 40-char receipt limit
            notes={
                "payment_id": payment.id,
                "case_id": case.id if case else "",
                "recovery_source": "razorpay_standard_checkout",
            },
        )
    except Exception as exc:  # SDK raises typed errors for auth/validation/network
        raise GatewayError(str(exc))

    order_id = order.get("id", "")
    recorder.record(
        db,
        case.id if case else None,
        "PAYMENT_ORDER_CREATED",
        payload={
            "provider": "razorpay",
            "order_id": order_id,
            "payment_id": payment.id,
            "amount_paise": amount_paise,
        },
        actor="SYSTEM",
    )

    return {
        "payment_id": payment.id,
        "case_id": case.id if case else None,
        "order_id": order_id,
        "amount": amount_inr,
        "amount_paise": amount_paise,
        "currency": _CURRENCY,
    }


# --------------------------------------------------------------------------------------
# 2. Verify the checkout signature, then settle through the deterministic ledger
# --------------------------------------------------------------------------------------
@traceable(name="service.razorpay.verify_and_settle", run_type="tool")
def verify_and_settle(
    db: Session,
    *,
    payment_id: str,
    order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> dict:
    if not is_configured():
        raise NotConfiguredError()

    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment is None:
        raise PaymentNotFoundError(payment_id)

    # ---- 1. Cryptographic verification BEFORE any state change -----------------------
    if not _signature_is_valid(order_id, razorpay_payment_id, razorpay_signature):
        raise InvalidSignatureError()

    # ---- 2. Idempotency: a verified repeat never double-settles ----------------------
    if payment.status == PaymentStatus.SUCCEEDED.value:
        existing = (
            db.query(RevenueRiskCase)
            .filter(RevenueRiskCase.payment_id == payment_id)
            .order_by(RevenueRiskCase.created_at.asc())
            .first()
        )
        return {
            "payment_id": payment.id,
            "case_id": existing.id if existing else None,
            "order_id": order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "status": "already_paid",
            "net_recovered": (existing.net_recovered_amount or 0.0) if existing else 0.0,
        }

    if payment.status != PaymentStatus.FAILED.value:
        raise InvalidStateError(
            f"Payment {payment_id} is not in a FAILED state — refusing to settle.",
            status_code=409,
        )

    # ---- 3. Money actually moved: record it in the domain ----------------------------
    payment.status = PaymentStatus.SUCCEEDED.value
    payment.error_code = None
    payment.error_message = None

    case = _open_case_for_payment(db, payment_id)
    net_recovered = 0.0

    if case is not None:
        totals = intervention_service.totals(db, case.id)
        cost_total = totals["cost_total"]
        discount_total = totals["discount_total"]
        gross = float(case.amount_at_risk or payment.amount)

        outcome = outcome_service.record_outcome(
            db,
            case_id=case.id,
            outcome_type=OutcomeType.RECOVERED_FULL.value,
            gross_recovered=gross,
            cost_total=cost_total,
            discount_total=discount_total,
            verified=True,  # signature-verified real payment, not a simulator roll
        )
        net_recovered = outcome.net_recovered

        case_service.set_net_recovered(db, case.id, net_recovered)
        case_service.set_current_action(db, case.id, None)
        case_service.set_status(db, case.id, CaseStatus.RECOVERED.value)

        recorder.record(
            db,
            case.id,
            "RECOVERED",  # same closing event type update_ledger emits for agent recoveries
            payload={
                "outcome_type": OutcomeType.RECOVERED_FULL.value,
                "gross_recovered": gross,
                "cost_total": cost_total,
                "discount_total": discount_total,
                "net_recovered": net_recovered,
                "verified_via": "razorpay_checkout_signature",
                "razorpay_payment_id": razorpay_payment_id,
            },
            actor="SYSTEM",
        )
    else:
        recorder.record(
            db,
            None,
            "PAYMENT_VERIFIED",
            payload={
                "payment_id": payment.id,
                "razorpay_payment_id": razorpay_payment_id,
                "verified_via": "razorpay_checkout_signature",
            },
            actor="SYSTEM",
        )

    return {
        "payment_id": payment.id,
        "case_id": case.id if case else None,
        "order_id": order_id,
        "razorpay_payment_id": razorpay_payment_id,
        "status": "success",
        "net_recovered": net_recovered,
    }
