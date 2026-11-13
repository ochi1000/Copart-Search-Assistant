import json

from backend.core.events import OperationEvent


def format_sse(event: OperationEvent) -> str:
    payload = json.dumps(
        event.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        f"id: {event.event_id}\n"
        f"event: {event.type}\n"
        f"data: {payload}\n\n"
    )


def heartbeat() -> str:
    return ": keep-alive\n\n"
