"""API schemas for the agent run (BUILDPLAN Phase 4)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class TimelineEntry(BaseModel):
    """One audit event, rendered for the case timeline (PRD §42)."""

    event_type: str
    actor: str
    payload: Dict[str, Any] = {}
    created_at: Optional[datetime] = None


class RunAgentResponse(BaseModel):
    """Result of ``POST /cases/{id}/run-agent`` — the final decision, outcome, and timeline."""

    case_id: str
    status: str
    diagnosis: Optional[Dict[str, Any]] = None
    chosen_action: Optional[str] = None
    expected_net: Optional[float] = None
    recovered: bool = False
    outcome_type: Optional[str] = None
    net_recovered: float = 0.0
    timeline: List[TimelineEntry] = []
