from contextlib import contextmanager
from contextvars import ContextVar
from typing import Awaitable, Callable, Iterator


EventPublisher = Callable[[str, dict], Awaitable[None]]
_publisher: ContextVar[EventPublisher | None] = ContextVar(
    "operation_event_publisher",
    default=None,
)


@contextmanager
def bind_event_publisher(publisher: EventPublisher) -> Iterator[None]:
    token = _publisher.set(publisher)
    try:
        yield
    finally:
        _publisher.reset(token)


async def emit_runtime_event(event_type: str, data: dict | None = None) -> None:
    publisher = _publisher.get()
    if publisher is not None:
        await publisher(event_type, data or {})
