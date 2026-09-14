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
from app.config import settings
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


class PaymentVerificationError(RazorpayServiceError):
    def __init__(self, detail: str):
        super().__init__(f"Payment verification failed: {detail}", status_code=400)


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


def _create_payment_link_on_gateway(
    amount_paise: int,
    description: str,
    notes: dict,
    reminder_enable: bool = False,
    expire_by: Optional[int] = None,
) -> dict:
    """Boundary around ``POST /v1/payment_links`` so tests never hit the network."""
    payload: dict = {
        "amount": amount_paise,
        "currency": _CURRENCY,
        "description": description,
        "reminder_enable": reminder_enable,
        "notes": notes,
    }
    if expire_by is not None:
        payload["expire_by"] = expire_by
    return _razorpay_client().payment_link.create(payload)


def _fetch_payment_on_gateway(payment_id: str) -> dict:
    """Boundary around ``GET /v1/payments/{id}`` so tests never hit the network."""
    return _razorpay_client().payment.fetch(payment_id)


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


def _open_case_for_payment(db: Session, payment_id: str, for_update: bool = False) -> Optional[RevenueRiskCase]:
    """The case working this payment that is not already closed/recovered."""
    query = (
        db.query(RevenueRiskCase)
        .filter(RevenueRiskCase.payment_id == payment_id)
        .filter(RevenueRiskCase.status.notin_(_CLOSED_STATUSES))
        .order_by(RevenueRiskCase.created_at.asc())
    )
    if for_update:
        query = query.with_for_update()
    return query.first()


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
    if order_id:
        from app.services import provider_object_service

        provider_object_service.record_object(
            db,
            case_id=case.id if case else None,
            object_type="order",
            provider_object_id=order_id,
            amount_paise=amount_paise,
            status="created",
        )

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


@traceable(name="service.razorpay.create_payment_link_for_case", run_type="tool")
def create_payment_link_for_case(
    db: Session,
    *,
    case_id: str,
    amount_inr: Optional[float] = None,
    description: Optional[str] = None,
    expire_by: Optional[int] = None,
    notes: Optional[dict] = None,
) -> dict:
    """Create a real Razorpay payment link for a case (B2.1).

    Enforces:
    - reminder_enable is False by default (Principle 7).
    - If ENABLE_NATIVE_REMINDERS is True, writes a matching Communication row to count against policy.
    - Writes a provider_objects row (status="created", object_type="payment_link").
    """
    if not is_configured():
        raise NotConfiguredError()

    case = case_service.get_case_row(db, case_id)
    if not case:
        raise InvalidStateError(f"Case {case_id} not found", status_code=404)

    payment = db.query(Payment).filter(Payment.id == case.payment_id).first() if case.payment_id else None
    amt = amount_inr if amount_inr is not None else float(case.amount_at_risk or (payment.amount if payment else 0.0))

    if amt < MIN_AMOUNT_INR:
        raise InvalidStateError(f"Amount {amt} INR is below Razorpay minimum of ₹{MIN_AMOUNT_INR}", status_code=400)

    amount_paise = int(round(amt * 100))
    link_notes = {
        "case_id": case.id,
        "payment_id": payment.id if payment else "",
        "receipt": payment.id if payment else case.id,
    }
    if notes:
        link_notes.update(notes)

    reminder_enable = bool(getattr(settings, "enable_native_reminders", False))

    try:
        link = _create_payment_link_on_gateway(
            amount_paise=amount_paise,
            description=description or f"Payment recovery for Case {case.id}",
            notes=link_notes,
            reminder_enable=reminder_enable,
            expire_by=expire_by,
        )
    except Exception as exc:
        raise GatewayError(str(exc))

    plink_id = link.get("id", "")
    short_url = link.get("short_url", "")

    # Principle 7 & DoD: If native reminders are ever enabled, record as Communication row
    if reminder_enable:
        from app.models.communication import Communication
        from app.domain.ids import generate_id

        comm = Communication(
            id=generate_id("COM", db),
            case_id=case.id,
            customer_id=case.customer_id,
            channel="SMS",
            recipient=case.customer_id,
            content=f"Razorpay native payment link reminder enabled for {plink_id}",
            status="SENT",
        )
        db.add(comm)
        db.commit()

    if plink_id:
        from app.services import provider_object_service

        provider_object_service.record_object(
            db,
            case_id=case.id,
            object_type="payment_link",
            provider_object_id=plink_id,
            amount_paise=amount_paise,
            status="created",
        )

    recorder.record(
        db,
        case.id,
        "PAYMENT_LINK_CREATED",
        payload={
            "provider": "razorpay",
            "payment_link_id": plink_id,
            "short_url": short_url,
            "amount_paise": amount_paise,
            "reminder_enable": reminder_enable,
        },
        actor="SYSTEM",
    )

    return {
        "case_id": case.id,
        "payment_link_id": plink_id,
        "short_url": short_url,
        "amount": amt,
        "amount_paise": amount_paise,
        "currency": _CURRENCY,
        "status": "created",
    }


@traceable(name="service.razorpay.fetch_payment", run_type="tool")
def fetch_payment(payment_id: str) -> dict:
    """Server-side read of payment details from Razorpay gateway (B2.1)."""
    if not is_configured():
        raise NotConfiguredError()
    try:
        return _fetch_payment_on_gateway(payment_id)
    except Exception as exc:
        raise GatewayError(str(exc))


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

    payment = db.query(Payment).filter(Payment.id == payment_id).with_for_update().first()
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

    # ---- 3. Server-side payment verification against gateway (Phase B3.1) ------------
    pay_data = fetch_payment(razorpay_payment_id)
    if not pay_data:
        raise PaymentVerificationError(f"Payment {razorpay_payment_id} not found on gateway")

    is_captured = pay_data.get("captured") is True or pay_data.get("status") == "captured"
    if not is_captured:
        raise PaymentVerificationError(
            f"Payment {razorpay_payment_id} is not captured on gateway (status: {pay_data.get('status')})"
        )

    if pay_data.get("currency") != _CURRENCY:
        raise PaymentVerificationError(
            f"Payment {razorpay_payment_id} currency '{pay_data.get('currency')}' does not match expected {_CURRENCY}"
        )

    gateway_order_id = pay_data.get("order_id")
    if gateway_order_id and gateway_order_id != order_id:
        raise PaymentVerificationError(
            f"Payment {razorpay_payment_id} order_id '{gateway_order_id}' does not match expected '{order_id}'"
        )

    amount_paise = pay_data.get("amount")
    expected_paise = int(round(float(payment.amount) * 100))
    if amount_paise is not None and int(amount_paise) < expected_paise:
        raise PaymentVerificationError(
            f"Payment {razorpay_payment_id} amount {amount_paise} paise is less than expected {expected_paise} paise"
        )

    case = _open_case_for_payment(db, payment_id, for_update=True)
    if case and order_id:
        from app.services import provider_object_service
        order_obj = provider_object_service.get_by_provider_id(db, order_id)
        if order_obj and order_obj.case_id and order_obj.case_id != case.id:
            raise PaymentVerificationError(
                f"Order {order_id} is bound to case {order_obj.case_id}, not {case.id}"
            )

    # ---- 4. Money actually moved: record it in the domain (Phase B3.2, B3.3) ---------
    fee_paise = int(pay_data.get("fee") or 0)
    settled_gross = float(amount_paise) / 100.0 if amount_paise is not None else float(payment.amount)

    payment.status = PaymentStatus.SUCCEEDED.value
    payment.error_code = None
    payment.error_message = None

    net_recovered = 0.0
    if case is not None:
        totals = intervention_service.totals(db, case.id)
        cost_total = totals["cost_total"]
        discount_total = totals["discount_total"]

        expected_gross = float(case.amount_at_risk or payment.amount)
        outcome_type = (
            OutcomeType.RECOVERED_PARTIAL.value
            if 0 < settled_gross < expected_gross
            else OutcomeType.RECOVERED_FULL.value
        )

        outcome = outcome_service.record_outcome(
            db,
            case_id=case.id,
            outcome_type=outcome_type,
            gross_recovered=settled_gross,
            cost_total=cost_total,
            discount_total=discount_total,
            gateway_fee_paise=fee_paise,
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
                "outcome_type": outcome_type,
                "gross_recovered": settled_gross,
                "cost_total": cost_total,
                "discount_total": discount_total,
                "gateway_fee": float(fee_paise) / 100.0,
                "fee_paise": fee_paise,
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
                "fee_paise": fee_paise,
                "verified_via": "razorpay_checkout_signature",
            },
            actor="SYSTEM",
        )

    # ---- 5. Record provider objects for instant reconciliation (A1.7, B3.3) -----------
    from app.services import provider_object_service

    actual_amount_paise = amount_paise if amount_paise is not None else int(round(float(payment.amount) * 100))
    if order_id:
        provider_object_service.update_status(db, provider_object_id=order_id, status="paid")
    if razorpay_payment_id:
        provider_object_service.record_object(
            db,
            case_id=case.id if case else None,
            object_type="payment",
            provider_object_id=razorpay_payment_id,
            amount_paise=actual_amount_paise,
            status="captured",
            fee_paise=fee_paise,
        )

    return {
        "payment_id": payment.id,
        "case_id": case.id if case else None,
        "order_id": order_id,
        "razorpay_payment_id": razorpay_payment_id,
        "status": "success",
        "net_recovered": net_recovered,
    }
