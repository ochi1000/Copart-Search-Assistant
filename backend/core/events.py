from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


TERMINAL_EVENT_TYPES = {"completed", "failed", "cancelled"}
PUBLIC_EVENT_TYPES = {
    "thinking",
    "search_started",
    "verification_required",
    "verification_completed",
    "completed",
    "failed",
    "cancelled",
}


class OperationEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    operation_id: str
    type: str
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    data: dict[str, Any] = Field(default_factory=dict)


class OperationSnapshot(BaseModel):
    operation_id: str
    session_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    event_count: int
    result: dict[str, Any] | None = None
