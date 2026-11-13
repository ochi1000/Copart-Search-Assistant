from collections.abc import Awaitable, Callable
from typing import Any

from backend.core.errors import (
    CopartUnavailable,
    InvalidSearchRequest,
    SearchExpired,
)


AsyncHandler = Callable[..., Awaitable[dict[str, Any]]]


class CopartService:
    """Public application boundary for Copart inventory operations."""

    def __init__(
        self,
        search_handler: AsyncHandler,
        detail_handler: AsyncHandler,
    ) -> None:
        self._search_handler = search_handler
        self._detail_handler = detail_handler

    async def search(self, **parameters: Any) -> dict[str, Any]:
        return self._unwrap(await self._search_handler(**parameters))

    async def show_more(self, **parameters: Any) -> dict[str, Any]:
        return await self.search(**parameters)

    async def refine(self, **parameters: Any) -> dict[str, Any]:
        return await self.search(**parameters)

    async def get_vehicle_details(
        self,
        lot_id_or_url: str,
        *,
        session_id: str,
    ) -> dict[str, Any]:
        result = await self._detail_handler(
            lot_id_or_url=lot_id_or_url,
            session_id=session_id,
        )
        return self._unwrap(result)

    @staticmethod
    def _unwrap(result: dict[str, Any]) -> dict[str, Any]:
        error = result.get("error")
        if not error:
            return result
        message = str(error)
        lowered = message.lower()
        if "missing or expired" in lowered:
            raise SearchExpired()
        if "valueerror" in lowered or "validation" in lowered:
            cleaned = message.split(":", 1)[-1].strip()
            raise InvalidSearchRequest(cleaned)
        raise CopartUnavailable()


def create_copart_service() -> CopartService:
    """Build the Copart feature boundary without depending on an API adapter."""
    from backend.copart.search import (
        get_copart_vehicle_details,
        search_copart_vehicles,
    )

    return CopartService(
        search_handler=search_copart_vehicles,
        detail_handler=get_copart_vehicle_details,
    )
