"""Live Signal Detection Service (Phase D2, D3).

Scans external provider states and webhooks to detect:
1. Abandoned Checkouts (unpaid/expired Razorpay payment links past abandon threshold)
2. Overdue Invoices (overdue/expired Razorpay invoices)
"""
from __future__ import annotations

import logging
from typing import List

from sqlalchemy.orm import Session

from app.audit import recorder
from app.domain.ids import generate_id
from app.models.case import RevenueRiskCase
from app.models.customer import Customer
from app.models.provider_object import ProviderObject
from app.observability import traceable
from app.schemas.enums import CaseStatus, CaseType
from app.services import provider_object_service, razorpay_service

logger = logging.getLogger("revive.detection")


@traceable(name="service.detection.scan_abandoned_checkouts", run_type="chain")
def scan_abandoned_checkouts(db: Session, *, abandon_after_hours: int = 2) -> List[str]:
    """Scan Razorpay payment links that remain unpaid or expired and create ABANDONED_CHECKOUT cases.

    Idempotent: payment links already linked to a case are skipped.
    """
    created_case_ids: List[str] = []

    # Query uncased payment links in provider_objects
    uncased_links = (
        db.query(ProviderObject)
        .filter(ProviderObject.object_type.in_(["payment_link", "link"]))
        .filter(ProviderObject.case_id.is_(None))
        .all()
    )

    for pobj in uncased_links:
        link_id = pobj.provider_object_id
        try:
            link_data = razorpay_service.fetch_payment_link(link_id)
        except Exception as exc:
            logger.warning(f"Could not fetch payment link {link_id} from gateway: {exc}")
            continue

        status = link_data.get("status", "")
        # Abandoned checkout if status is expired or cancelled/unpaid
        if status in ("expired", "cancelled", "created"):
            amount_paise = link_data.get("amount") or pobj.amount_paise or 0
            amount_inr = float(amount_paise) / 100.0 if amount_paise else 0.0

            cust_data = link_data.get("customer") or {}
            cust_email = cust_data.get("email") or "shopper@example.com"
            cust_phone = cust_data.get("contact") or "+919999999999"
            cust_name = cust_data.get("name") or "Abandoned Shopper"

            cust = db.query(Customer).filter(Customer.email == cust_email).first()
            if not cust:
                cust = Customer(
                    id=generate_id("CUS", db),
                    name=cust_name,
                    email=cust_email,
                    phone=cust_phone,
                    origin="live",
                    risk_score=0.5,
                )
                db.add(cust)
                db.flush()

            case = RevenueRiskCase(
                id=generate_id("RR", db),
                customer_id=cust.id,
                payment_id=None,
                case_type=CaseType.ABANDONED_CHECKOUT.value,
                origin="live",
                status=CaseStatus.DETECTED.value,
                amount_at_risk=amount_inr,
                priority="HIGH" if amount_inr > 5000 else "MEDIUM",
                risk_score=0.5,
            )
            db.add(case)
            db.flush()

            pobj.case_id = case.id
            pobj.status = status
            db.flush()

            recorder.record(
                db,
                case.id,
                "ABANDONED_CHECKOUT_DETECTED",
                payload={"payment_link_id": link_id, "amount": amount_inr, "status": status},
                actor="SYSTEM",
            )
            created_case_ids.append(case.id)

    if created_case_ids:
        db.commit()

    return created_case_ids


@traceable(name="service.detection.scan_overdue_invoices", run_type="chain")
def scan_overdue_invoices(db: Session, *, limit: int = 50) -> List[str]:
    """Poll Razorpay Invoices API for overdue or expired invoices and create OVERDUE_INVOICE cases.

    Idempotent: invoices already registered or cased are skipped.
    """
    created_case_ids: List[str] = []

    try:
        invoices_resp = razorpay_service.list_invoices(count=limit)
    except Exception as exc:
        logger.warning(f"Could not list invoices from gateway: {exc}")
        return []

    items = invoices_resp.get("items", []) if isinstance(invoices_resp, dict) else []

    for inv in items:
        inv_id = inv.get("id")
        if not inv_id:
            continue

        # Check if already tracked
        pobj = provider_object_service.get_by_provider_id(db, inv_id)
        if pobj and pobj.case_id:
            continue

        status = inv.get("status", "")
        # Only ingest overdue/expired/issued past due
        if status in ("expired", "unpaid", "overdue"):
            amount_paise = inv.get("amount") or 0
            amount_inr = float(amount_paise) / 100.0 if amount_paise else 0.0

            cust_email = inv.get("customer_email") or "invoice_client@example.com"
            cust_phone = inv.get("customer_contact") or "+919999999999"
            cust_name = inv.get("customer_name") or "Invoice Client"

            cust = db.query(Customer).filter(Customer.email == cust_email).first()
            if not cust:
                cust = Customer(
                    id=generate_id("CUS", db),
                    name=cust_name,
                    email=cust_email,
                    phone=cust_phone,
                    origin="live",
                    risk_score=0.5,
                )
                db.add(cust)
                db.flush()

            case = RevenueRiskCase(
                id=generate_id("RR", db),
                customer_id=cust.id,
                payment_id=None,
                case_type=CaseType.OVERDUE_INVOICE.value,
                origin="live",
                status=CaseStatus.DETECTED.value,
                amount_at_risk=amount_inr,
                priority="HIGH" if amount_inr > 5000 else "MEDIUM",
                risk_score=0.5,
            )
            db.add(case)
            db.flush()

            if not pobj:
                pobj = provider_object_service.record_object(
                    db,
                    case_id=case.id,
                    object_type="invoice",
                    provider_object_id=inv_id,
                    amount_paise=amount_paise,
                    status=status,
                )
            else:
                pobj.case_id = case.id
                pobj.status = status
                db.flush()

            recorder.record(
                db,
                case.id,
                "OVERDUE_INVOICE_DETECTED",
                payload={"invoice_id": inv_id, "amount": amount_inr, "status": status},
                actor="SYSTEM",
            )
            created_case_ids.append(case.id)

    if created_case_ids:
        db.commit()

    return created_case_ids
