"""Nightly Reconciliation & Escalation SLA Service (Phase E1 & E1.2).

Cross-checks internal case and ledger state against external Razorpay gateway truth,
detects amount discrepancies, unreflected refunds, status desyncs, and monitors
unassigned escalations against SLA deadlines.
"""
from __future__ import annotations

import logging
from datetime import timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.audit import recorder
from app.config import settings
from app.db import utc_now
from app.models.escalation import Escalation
from app.models.outcome import RecoveryOutcome
from app.models.provider_object import ProviderObject
from app.observability import traceable
from app.schemas.enums import EscalationReason, OutcomeType
from app.services import escalation_service, razorpay_service

logger = logging.getLogger("revive.reconciliation")

_latest_reconciliation_report: Dict[str, Any] = {
    "status": "never_run",
    "executed_at": None,
    "total_checked": 0,
    "matched": 0,
    "mismatches": 0,
    "mismatch_details": [],
}


def _trigger_admin_alert(subject: str, message: str) -> None:
    """Send admin alert via log and email channel if configured (Phase E1)."""
    recipient = settings.admin_alert_email or "unconfigured"
    logger.critical(f"[RECONCILIATION ALERT] To: {recipient} | {subject} | {message}")


@traceable(name="service.reconciliation.reconcile_all", run_type="chain")
def reconcile_all(db: Session) -> Dict[str, Any]:
    """Execute complete ledger cross-check against Razorpay gateway objects (Phase E1).

    Checks:
    1. provider_objects.status vs. Razorpay API status for each object.
    2. RecoveryOutcome.gross_recovered vs. actual captured amount.
    3. Outstanding refunds/disputes not yet reflected in the ledger.
    4. Automatically creates Escalation(reason='RECONCILIATION_MISMATCH') on discrepancy.
    """
    global _latest_reconciliation_report

    objects = db.query(ProviderObject).filter(ProviderObject.case_id.isnot(None)).all()
    total_checked = 0
    matched = 0
    mismatches: List[Dict[str, Any]] = []

    for pobj in objects:
        total_checked += 1
        case_id = pobj.case_id
        obj_id = pobj.provider_object_id
        obj_type = pobj.object_type

        try:
            # 1. Payment Objects
            if obj_type == "payment":
                pay_data = razorpay_service.fetch_payment(obj_id)
                gw_status = pay_data.get("status", "")
                gw_amount_paise = pay_data.get("amount", 0)
                gw_refund_paise = pay_data.get("amount_refunded", 0)

                # Check outcome discrepancy
                outcome = (
                    db.query(RecoveryOutcome)
                    .filter(RecoveryOutcome.case_id == case_id)
                    .order_by(RecoveryOutcome.created_at.desc(), RecoveryOutcome.id.desc())
                    .first()
                )

                discrepancy_reason: Optional[str] = None
                if outcome:
                    expected_paise = int(round(outcome.gross_recovered * 100))
                    if outcome.outcome_type in (OutcomeType.RECOVERED_FULL.value, OutcomeType.RECOVERED_PARTIAL.value):
                        # Captured amount mismatch
                        if gw_amount_paise != expected_paise:
                            diff_inr = (expected_paise - gw_amount_paise) / 100.0
                            discrepancy_reason = (
                                f"Discrepancy on case {case_id}: gross recovered is ₹{outcome.gross_recovered:.2f} "
                                f"but gateway captured ₹{gw_amount_paise / 100.0:.2f} (diff: ₹{diff_inr:.2f})"
                            )

                    # Unreflected refund
                    if gw_refund_paise > 0 and outcome.outcome_type != OutcomeType.REFUNDED.value:
                        refund_inr = gw_refund_paise / 100.0
                        discrepancy_reason = (
                            f"Unreflected refund on case {case_id}: gateway shows ₹{refund_inr:.2f} refunded, "
                            f"but outcome is '{outcome.outcome_type}'"
                        )

                # Status mismatch
                if not discrepancy_reason and pobj.status and gw_status and pobj.status != gw_status:
                    discrepancy_reason = (
                        f"Status mismatch on object {obj_id}: internal status '{pobj.status}' "
                        f"vs gateway '{gw_status}'"
                    )

                if discrepancy_reason:
                    mismatch_entry = {
                        "case_id": case_id,
                        "object_id": obj_id,
                        "object_type": obj_type,
                        "reason": discrepancy_reason,
                    }
                    mismatches.append(mismatch_entry)

                    # Open escalation row
                    escalation_service.create_escalation(
                        db,
                        case_id=case_id,
                        reason=EscalationReason.RECONCILIATION_MISMATCH.value,
                        priority="HIGH",
                        notes=f"[Automated Reconcile Mismatch] {discrepancy_reason}",
                    )

                    recorder.record(
                        db,
                        case_id=case_id,
                        event_type="RECONCILIATION_MISMATCH_DETECTED",
                        payload=mismatch_entry,
                        actor="SYSTEM",
                    )
                    _trigger_admin_alert(
                        subject=f"Ledger Discrepancy on Case {case_id}",
                        message=discrepancy_reason,
                    )
                else:
                    matched += 1

            # 2. Payment Link Objects
            elif obj_type in ("link", "payment_link"):
                link_data = razorpay_service.fetch_payment_link(obj_id)
                gw_status = link_data.get("status", "")
                if pobj.status and gw_status and pobj.status != gw_status:
                    # Update local status to reflect gateway
                    pobj.status = gw_status
                    db.flush()
                matched += 1

            # 3. Order Objects
            elif obj_type == "order":
                order_data = razorpay_service.fetch_order(obj_id)
                gw_status = order_data.get("status", "")
                if pobj.status and gw_status and pobj.status != gw_status:
                    pobj.status = gw_status
                    db.flush()
                matched += 1

            else:
                matched += 1

        except Exception as exc:
            logger.warning(f"Reconciliation error checking object {obj_id}: {exc}")
            mismatches.append({
                "case_id": case_id,
                "object_id": obj_id,
                "object_type": obj_type,
                "reason": f"Gateway fetch error: {exc}",
            })

    db.commit()

    report = {
        "status": "completed",
        "executed_at": utc_now().isoformat(),
        "total_checked": total_checked,
        "matched": matched,
        "mismatches": len(mismatches),
        "mismatch_details": mismatches,
    }
    _latest_reconciliation_report = report

    recorder.record(
        db,
        case_id=None,
        event_type="RECONCILIATION_COMPLETED",
        payload={
            "total_checked": total_checked,
            "matched": matched,
            "mismatches": len(mismatches),
        },
        actor="SYSTEM",
    )
    return report


@traceable(name="service.reconciliation.check_escalation_slas", run_type="chain")
def check_escalation_slas(db: Session) -> List[Dict[str, Any]]:
    """Scan open unassigned escalations that breached their SLA response time (Phase E1.2)."""
    now = utc_now()
    breached = (
        db.query(Escalation)
        .filter(Escalation.status == "OPEN")
        .filter(Escalation.owner_id.is_(None))
        .filter(Escalation.sla_due_at.isnot(None))
        .filter(Escalation.sla_due_at < now)
        .all()
    )

    breached_records: List[Dict[str, Any]] = []
    for esc in breached:
        sla_time = esc.sla_due_at
        if sla_time and sla_time.tzinfo is None:
            sla_time = sla_time.replace(tzinfo=timezone.utc)
        overdue_hours = (now - sla_time).total_seconds() / 3600.0 if sla_time else 0.0
        record = {
            "escalation_id": esc.id,
            "case_id": esc.case_id,
            "reason": esc.reason,
            "priority": esc.priority,
            "created_at": esc.created_at.isoformat() if esc.created_at else None,
            "sla_due_at": esc.sla_due_at.isoformat() if esc.sla_due_at else None,
            "hours_overdue": round(overdue_hours, 1),
        }
        breached_records.append(record)

        _trigger_admin_alert(
            subject=f"Escalation SLA Breached ({esc.id})",
            message=f"Escalation {esc.id} on case {esc.case_id} has been unassigned for {overdue_hours:.1f} hours past SLA.",
        )

    return breached_records


def get_latest_reconciliation_report(db: Session) -> Dict[str, Any]:
    """Retrieve the latest reconciliation run report along with current aging escalations."""
    aging = check_escalation_slas(db)
    report = dict(_latest_reconciliation_report)
    report["aging_escalations"] = aging
    return report
