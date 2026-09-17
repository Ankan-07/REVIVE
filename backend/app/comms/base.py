"""Base interfaces and data structures for communications (Phase C)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session


class CommsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    success: bool
    communication_id: Optional[str] = None
    provider: str = "mock_comms"
    provider_message_id: Optional[str] = None
    channel: str
    recipient: str
    template_id: Optional[str] = None
    content: Optional[str] = None
    error: Optional[str] = None


class CommsProvider(ABC):
    """Abstract interface for customer communications delivery."""

    @abstractmethod
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
        """Deliver or record a communication event."""
        pass
