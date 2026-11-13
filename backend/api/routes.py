from uuid import uuid4

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from backend.agent.service import AgentService
from backend.api.operations import OperationManager
from backend.api.schemas import (
    CancelResponse,
    HealthResponse,
    MessageRequest,
    OperationAccepted,
)
from backend.api.streaming import format_sse, heartbeat
from backend.core.events import OperationSnapshot


def build_router(
    agent: AgentService,
    operations: OperationManager,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @router.post("/messages", response_model=OperationAccepted, status_code=202)
    async def create_message(request: MessageRequest) -> OperationAccepted:
        session_id = request.session_id or uuid4().hex

        async def runner(publish):
            return await agent.handle_message(
                request.message.strip(),
                session_id,
                publish,
            )

        operation = await operations.start(session_id, runner)
        return OperationAccepted(
            operation_id=operation.operation_id,
            session_id=session_id,
        )

    @router.get(
        "/operations/{operation_id}",
        response_model=OperationSnapshot,
    )
    async def operation_status(operation_id: str) -> OperationSnapshot:
        return await operations.snapshot(operation_id)

    @router.post(
        "/operations/{operation_id}/cancel",
        response_model=CancelResponse,
    )
    async def cancel_operation(operation_id: str) -> CancelResponse:
        operation = await operations.cancel(operation_id)
        return CancelResponse(
            operation_id=operation_id,
            status=(
                operation.status
                if operation.status in {"completed", "failed", "cancelled"}
                else "cancelling"
            ),
        )

    @router.get("/operations/{operation_id}/events")
    async def operation_events(
        operation_id: str,
        start_index: int | None = Query(default=None, ge=0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        await operations.get(operation_id)
        cursor = start_index
        if cursor is None:
            cursor = (
                await operations.event_index_after(operation_id, last_event_id)
                if last_event_id
                else 0
            )

        async def event_stream():
            async for event in operations.events(
                operation_id,
                cursor,
                public_only=True,
            ):
                yield heartbeat() if event is None else format_sse(event)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
