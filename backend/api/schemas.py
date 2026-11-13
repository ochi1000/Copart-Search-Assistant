from typing import Any

from pydantic import BaseModel, Field


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=128)


class OperationAccepted(BaseModel):
    operation_id: str
    session_id: str
    status: str = "accepted"


class CancelResponse(BaseModel):
    operation_id: str
    status: str


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "copart-assistant"


class PublicErrorResponse(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None
