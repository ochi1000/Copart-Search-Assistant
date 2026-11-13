import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from backend.core.errors import ApplicationError, OperationNotFound
from backend.core.events import (
    PUBLIC_EVENT_TYPES,
    TERMINAL_EVENT_TYPES,
    OperationEvent,
    OperationSnapshot,
)
from backend.core.runtime import EventPublisher, bind_event_publisher


logger = logging.getLogger(__name__)
OperationRunner = Callable[[EventPublisher], Awaitable[dict[str, Any] | None]]


@dataclass
class Operation:
    operation_id: str
    session_id: str
    created_at: datetime
    updated_at: datetime
    status: str = "accepted"
    events: list[OperationEvent] = field(default_factory=list)
    result: dict[str, Any] | None = None
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task | None = None


class OperationManager:
    def __init__(self) -> None:
        self._operations: dict[str, Operation] = {}
        self._lock = asyncio.Lock()

    async def start(self, session_id: str, runner: OperationRunner) -> Operation:
        now = datetime.now(timezone.utc)
        operation = Operation(
            operation_id=uuid4().hex,
            session_id=session_id,
            created_at=now,
            updated_at=now,
        )
        async with self._lock:
            self._operations[operation.operation_id] = operation
        operation.task = asyncio.create_task(
            self._run(operation, runner),
            name=f"copart-operation-{operation.operation_id}",
        )
        return operation

    async def _run(self, operation: Operation, runner: OperationRunner) -> None:
        async def publish(event_type: str, data: dict | None = None) -> None:
            await self.publish(operation.operation_id, event_type, data or {})

        try:
            operation.status = "running"
            await publish("accepted", {"session_id": operation.session_id})
            with bind_event_publisher(publish):
                operation.result = await runner(publish)
            await publish("completed", {"result": operation.result or {}})
        except asyncio.CancelledError:
            await publish(
                "cancelled",
                {"message": "The operation was cancelled."},
            )
        except ApplicationError as exc:
            await publish("failed", exc.public_data())
        except Exception:
            logger.exception("Unhandled operation failure: %s", operation.operation_id)
            await publish(
                "failed",
                {
                    "code": "INTERNAL_ERROR",
                    "message": "The request could not be completed. Please try again.",
                    "retryable": True,
                },
            )

    async def publish(
        self,
        operation_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> OperationEvent:
        operation = await self.get(operation_id)
        event = OperationEvent(
            operation_id=operation_id,
            type=event_type,
            data=data,
        )
        async with operation.condition:
            operation.events.append(event)
            operation.updated_at = datetime.now(timezone.utc)
            operation.status = event_type if event_type in TERMINAL_EVENT_TYPES else "running"
            operation.condition.notify_all()
        return event

    async def get(self, operation_id: str) -> Operation:
        async with self._lock:
            operation = self._operations.get(operation_id)
        if operation is None:
            raise OperationNotFound()
        return operation

    async def snapshot(self, operation_id: str) -> OperationSnapshot:
        operation = await self.get(operation_id)
        return OperationSnapshot(
            operation_id=operation.operation_id,
            session_id=operation.session_id,
            status=operation.status,
            created_at=operation.created_at,
            updated_at=operation.updated_at,
            event_count=len(operation.events),
            result=operation.result,
        )

    async def cancel(self, operation_id: str) -> Operation:
        operation = await self.get(operation_id)
        if operation.status in TERMINAL_EVENT_TYPES:
            return operation
        if operation.task is not None:
            operation.task.cancel()
            await asyncio.sleep(0)
            if operation.task.done() and operation.status not in TERMINAL_EVENT_TYPES:
                await self.publish(
                    operation_id,
                    "cancelled",
                    {"message": "The operation was cancelled."},
                )
        return operation

    async def event_index_after(
        self,
        operation_id: str,
        event_id: str,
    ) -> int:
        operation = await self.get(operation_id)
        for index, event in enumerate(operation.events):
            if event.event_id == event_id:
                return index + 1
        return 0

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = [
                operation.task
                for operation in self._operations.values()
                if operation.task is not None and not operation.task.done()
            ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def events(
        self,
        operation_id: str,
        start_index: int = 0,
        heartbeat_seconds: float = 15.0,
        public_only: bool = False,
    ) -> AsyncIterator[OperationEvent | None]:
        operation = await self.get(operation_id)
        index = max(0, start_index)
        while True:
            while index < len(operation.events):
                event = operation.events[index]
                index += 1
                if public_only and event.type not in PUBLIC_EVENT_TYPES:
                    continue
                yield event
                if event.type in TERMINAL_EVENT_TYPES:
                    return

            if operation.status in TERMINAL_EVENT_TYPES:
                return

            try:
                async with operation.condition:
                    if index < len(operation.events):
                        continue
                    if operation.status in TERMINAL_EVENT_TYPES:
                        return
                    await asyncio.wait_for(
                        operation.condition.wait(),
                        timeout=heartbeat_seconds,
                    )
            except TimeoutError:
                yield None
