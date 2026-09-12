"""Schemas for background jobs and async execution (Phase A4)."""
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict


class JobRead(BaseModel):
    id: str
    job_type: str
    status: str
    case_id: Optional[str] = None
    payload_json: Optional[Dict[str, Any]] = None
    result_json: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    traceback: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class JobEnqueueResponse(BaseModel):
    job_id: str
    status: str
    status_url: str
    case_id: Optional[str] = None
