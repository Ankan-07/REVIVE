"""MockCommsProvider implementation for zero-compliance communication outreach (Phase C)."""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.comms.base import CommsProvider, CommsResult
from app.comms.templates import render_template
from app.db import utc_now
from app.domain.ids import generate_id
from app.models.communication import Communication
from app.observability import traceable


def _validate_recipient(recipient: str, channel: str) -> bool:
    if not recipient or not isinstance(recipient, str):
        return False
    rec = recipient.strip()
    if channel.upper() == "EMAIL":
        return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", rec))
    elif channel.upper() in ("SMS", "WHATSAPP"):
        # E.164 phone or digits
        return bool(re.match(r"^\+?[0-9]{8,15}$", rec.replace("-", "").replace(" ", "")))
    return True


class MockCommsProvider(CommsProvider):
    """In-memory, database-tracked communication provider.
    
    Eliminates external DLT and domain compliance requirements while preserving
    full Communication auditing, template rendering, and policy tracking.
    """

    @traceable(name="comms.mock.send", run_type="tool")
    def send(
        self,
        db: Session,
        *,
        case_id: str,
        customer_id: str,
        recipient: str,
        channel: str,
        template_id: str,
        context: Dict[str, Any],
    ) -> CommsResult:
        if not _validate_recipient(recipient, channel):
            return CommsResult(
                success=False,
                channel=channel,
                recipient=recipient,
                template_id=template_id,
                error=f"Invalid recipient format for channel {channel}: '{recipient}'",
            )

        content = render_template(template_id, context)
        provider_msg_id = f"mock_msg_{uuid.uuid4().hex[:16]}"
        comm_id = generate_id("COM", db)
        now = utc_now()

        comm = Communication(
            id=comm_id,
            case_id=case_id,
            customer_id=customer_id,
            channel=channel.upper(),
            recipient=recipient.strip(),
            template_id=template_id,
            content=content,
            status="DELIVERED",
            sent_at=now,
            provider="mock_comms",
            provider_message_id=provider_msg_id,
            delivered_at=now,
        )
        db.add(comm)
        db.commit()
        db.refresh(comm)

        return CommsResult(
            success=True,
            communication_id=comm_id,
            provider="mock_comms",
            provider_message_id=provider_msg_id,
            channel=channel.upper(),
            recipient=recipient.strip(),
            template_id=template_id,
            content=content,
        )
