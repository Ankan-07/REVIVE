"""Provider Object registry service (PRD §38, Phase A1.7).

Maintains a unified mapping of cases to external Razorpay provider objects (orders,
payment links, payments, invoices) with exact paise amounts and fees.
"""
from typing import List, Optional
from sqlalchemy.orm import Session
from app.domain.ids import generate_id
from app.models.provider_object import ProviderObject
from app.observability import traceable


@traceable(name="service.provider_object.record", run_type="tool")
def record_object(
    db: Session,
    *,
    case_id: Optional[str],
    object_type: str,
    provider_object_id: str,
    amount_paise: Optional[int] = None,
    status: Optional[str] = None,
    fee_paise: Optional[int] = None,
) -> ProviderObject:
    """Record or update an external provider object mapped to a case."""
    existing = (
        db.query(ProviderObject)
        .filter(ProviderObject.provider_object_id == provider_object_id)
        .first()
    )
    if existing:
        if case_id is not None:
            existing.case_id = case_id
        if status is not None:
            existing.status = status
        if amount_paise is not None:
            existing.amount_paise = amount_paise
        if fee_paise is not None:
            existing.fee_paise = fee_paise
        db.commit()
        db.refresh(existing)
        return existing

    obj = ProviderObject(
        id=generate_id("POBJ", db),
        case_id=case_id,
        object_type=object_type,
        provider_object_id=provider_object_id,
        amount_paise=amount_paise,
        status=status,
        fee_paise=fee_paise,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@traceable(name="service.provider_object.update_status", run_type="tool")
def update_status(
    db: Session,
    *,
    provider_object_id: str,
    status: str,
    fee_paise: Optional[int] = None,
) -> Optional[ProviderObject]:
    """Update the status and optional fee for a registered provider object."""
    obj = (
        db.query(ProviderObject)
        .filter(ProviderObject.provider_object_id == provider_object_id)
        .first()
    )
    if obj:
        obj.status = status
        if fee_paise is not None:
            obj.fee_paise = fee_paise
        db.commit()
        db.refresh(obj)
    return obj


@traceable(name="service.provider_object.get_by_provider_id", run_type="tool")
def get_by_provider_id(db: Session, provider_object_id: str) -> Optional[ProviderObject]:
    """Look up a provider object by external provider ID."""
    return (
        db.query(ProviderObject)
        .filter(ProviderObject.provider_object_id == provider_object_id)
        .first()
    )


@traceable(name="service.provider_object.list_for_case", run_type="tool")
def list_for_case(db: Session, case_id: str) -> List[ProviderObject]:
    """List all provider objects mapped to a case."""
    return (
        db.query(ProviderObject)
        .filter(ProviderObject.case_id == case_id)
        .order_by(ProviderObject.created_at.asc())
        .all()
    )
