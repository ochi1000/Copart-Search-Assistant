import asyncio
import copy
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from backend.copart.service import CopartService
from backend.core.errors import (
    InvalidSearchRequest,
    LLMRateLimited,
    LLMUnavailable,
)
from backend.core.runtime import EventPublisher
from backend.copart.models import VehicleFilterConstraints


SYSTEM_PROMPT = """You are a calm, concise Copart vehicle-search assistant.
Use search_copart_vehicles for inventory requests and follow-up refinements.
For 'show more', pass the saved search_id and next_offset.
For refinements, pass search_id and only changed fields. Use clear_filters to remove one.
Use state for one state and locations for multiple states or yards.
'From YEAR' means min_year. Only use both years when the user clearly means that exact year.
Use the Electric Vehicles or Hybrid featured item for electric or hybrid requests.
Only apply filters the user actually requested. Do not turn generic words such as
'car', 'cars', 'vehicle', or 'vehicles' into a vehicle_types filter.
Never call the same search twice after it succeeds.
After tool results, respond with a short natural summary. The frontend renders vehicle cards and images, so do not reproduce full tables or raw image URLs.
For a successful exact inventory search, do not describe individual listings; the
frontend cards are the response.
Keep the tone warm and matter-of-fact. Do not apologize for criteria the user did not
request. If a requested filter could not be confirmed, gently mention it once and
present any similar results that were found.
Use get_copart_vehicle_details for a lot number or selected vehicle.
"""


@dataclass
class AgentSession:
    search_state: dict[str, Any] | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class AgentService:
    def __init__(self, copart: CopartService) -> None:
        provider = os.getenv("LLM_PROVIDER", "groq").lower()
        if provider == "groq":
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise RuntimeError("GROQ_API_KEY is not configured")
            self.model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url="https://api.groq.com/openai/v1",
            )
        else:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY is not configured")
            self.model = os.getenv("OPENAI_MODEL", "gpt-4o")
            self.client = AsyncOpenAI(api_key=api_key)

        self.copart = copart
        self._sessions: dict[str, AgentSession] = {}
        self._sessions_lock = asyncio.Lock()
        self.tools = self._build_tools()

    async def handle_message(
        self,
        message: str,
        session_id: str,
        publish: EventPublisher,
    ) -> dict[str, Any]:
        session = await self._get_session(session_id)
        async with session.lock:
            await publish("thinking", {})
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": SYSTEM_PROMPT},
            ]
            if session.search_state:
                messages.append({
                    "role": "system",
                    "content": (
                        "Current search state: "
                        + json.dumps(
                            session.search_state,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    ),
                })
            messages.append({"role": "user", "content": message})

            successful_search = False
            search_result: dict[str, Any] | None = None
            vehicle_detail: dict[str, Any] | None = None
            for _ in range(5):
                response = await self._complete(messages)
                assistant = response.choices[0].message
                assistant_dict = assistant.model_dump(exclude_none=True)
                messages.append(assistant_dict)

                if not assistant.tool_calls:
                    reply = self._grounded_reply(
                        assistant.content or "I could not complete that response.",
                        search_result,
                    )
                    completed = {
                        "message": reply,
                        "search_id": (
                            session.search_state.get("search_id")
                            if session.search_state
                            else None
                        ),
                    }
                    if search_result is not None:
                        completed["search"] = search_result
                    if vehicle_detail is not None:
                        completed["vehicle"] = vehicle_detail
                    return completed

                for tool_call in assistant.tool_calls:
                    try:
                        arguments = json.loads(tool_call.function.arguments or "{}")
                        if not isinstance(arguments, dict):
                            raise ValueError("arguments must be an object")
                    except (json.JSONDecodeError, ValueError) as exc:
                        messages.append(self._tool_message(
                            tool_call.id,
                            {"error": f"Invalid tool arguments: {exc}"},
                        ))
                        continue

                    tool_name = tool_call.function.name
                    if tool_name == "search_copart_vehicles":
                        if successful_search:
                            result = {"error": "Search already completed for this message."}
                        else:
                            arguments["session_id"] = session_id
                            arguments["max_results"] = min(
                                int(arguments.get("max_results", 4)),
                                int(os.getenv("CHAT_RESULTS_PER_PAGE", "4")),
                            )
                            await publish(
                                "search_started",
                                {"parameters": self._safe_parameters(arguments)},
                            )
                            result = await self.copart.search(**arguments)
                            successful_search = True
                            search_result = result
                            session.search_state = self._search_state(result)
                            await publish("search_ready", {
                                "search_id": result.get("search_id"),
                                "count_returned": result.get("count_returned", 0),
                                "has_more": result.get("has_more", False),
                            })
                        messages.append(self._tool_message(
                            tool_call.id,
                            self._compact_search_result(result),
                        ))
                    elif tool_name == "get_copart_vehicle_details":
                        lot = str(arguments.get("lot_id_or_url") or "").strip()
                        if not lot:
                            raise InvalidSearchRequest("A Copart lot number is required.")
                        await publish("detail_started", {"lot_id_or_url": lot})
                        result = await self.copart.get_vehicle_details(
                            lot,
                            session_id=session_id,
                        )
                        vehicle_detail = result
                        await publish(
                            "detail_ready",
                            {
                                "lot_url": result.get("lot_url"),
                                "photo_count": result.get("photo_count", 0),
                            },
                        )
                        messages.append(self._tool_message(
                            tool_call.id,
                            self._primary_detail(result),
                        ))
                    else:
                        messages.append(self._tool_message(
                            tool_call.id,
                            {"error": f"Unknown tool: {tool_name}"},
                        ))

            raise InvalidSearchRequest(
                "The assistant could not finish the request within its tool limit."
            )

    async def _complete(self, messages: list[dict[str, Any]]):
        try:
            return await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools,
                tool_choice="auto",
                max_tokens=900,
            )
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code in {413, 429}:
                raise LLMRateLimited() from exc
            if status_code in {401, 403, 500, 502, 503, 504}:
                raise LLMUnavailable() from exc
            if type(exc).__name__ in {
                "APIConnectionError",
                "APITimeoutError",
                "ConnectError",
            }:
                raise LLMUnavailable() from exc
            raise

    async def _get_session(self, session_id: str) -> AgentSession:
        async with self._sessions_lock:
            return self._sessions.setdefault(session_id, AgentSession())

    @staticmethod
    def _tool_message(tool_call_id: str, payload: dict) -> dict:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        }

    @staticmethod
    def _safe_parameters(parameters: dict) -> dict:
        return {
            key: value
            for key, value in parameters.items()
            if key != "session_id"
        }

    @staticmethod
    def _compact_vehicle(vehicle: dict) -> dict:
        keys = (
            "title",
            "lot_number",
            "title_status",
            "damage",
            "odometer",
            "yard_location",
            "current_bid",
            "buy_it_now_price",
            "link",
        )
        return {key: vehicle.get(key) for key in keys if vehicle.get(key)}

    @classmethod
    def _compact_search_result(cls, result: dict) -> dict:
        keys = (
            "query",
            "search_id",
            "active_filters",
            "match_status",
            "notice",
            "filter_warnings",
            "next_offset",
            "has_more",
            "has_cached_more",
            "source_has_more",
        )
        compact = {key: result.get(key) for key in keys if key in result}
        compact["vehicles"] = [
            cls._compact_vehicle(vehicle)
            for vehicle in result.get("vehicles", [])
        ]
        return compact

    @classmethod
    def _search_state(cls, result: dict) -> dict:
        state = cls._compact_search_result(result)
        state["last_page_lot_ids"] = [
            vehicle.get("lot_number")
            for vehicle in result.get("vehicles", [])
            if vehicle.get("lot_number")
        ]
        state.pop("vehicles", None)
        return state

    @staticmethod
    def _primary_detail(result: dict) -> dict:
        keys = (
            "lot_url",
            "vehicle_title",
            "vin",
            "condition",
            "auction_date",
            "yard_location",
            "photo_count",
            "primary_image_url",
            "image_status",
        )
        return {key: result.get(key) for key in keys if result.get(key) not in (None, "")}

    @staticmethod
    def _grounded_reply(reply: str, search_result: dict | None) -> str:
        """Keep user-facing claims aligned with Copart's filter report."""
        if not search_result:
            return reply

        count = int(search_result.get("count_returned") or 0)
        match_status = search_result.get("match_status")
        warnings = search_result.get("filter_warnings") or []

        if match_status == "no_matches":
            return (
                "I couldn't find a close match this time. You could try adjusting "
                "one of your preferences."
            )
        if match_status == "close_matches":
            return (
                "I didn't find an exact match for every preference, but I found "
                f"{count} close option{'s' if count != 1 else ''} that may still "
                "be helpful."
            )
        if warnings or match_status == "partial_matches":
            filter_name = AgentService._warning_filter_name(warnings)
            subject = (
                f"the {filter_name} filter"
                if filter_name
                else "one of your filters"
            )
            return (
                f"I couldn't confirm {subject} this time, but I found {count} similar "
                f"option{'s' if count != 1 else ''} that may still be useful."
            )
        return AgentService._without_duplicate_listing_text(reply, search_result)

    @staticmethod
    def _without_duplicate_listing_text(reply: str, search_result: dict) -> str:
        """Keep the conversational response while cards carry listing details."""
        vehicles = search_result.get("vehicles") or []
        listing_identifiers = []
        for vehicle in vehicles:
            for value in (vehicle.get("title"), vehicle.get("lot_number")):
                normalized_value = re.sub(
                    r"[^a-z0-9]+",
                    " ",
                    str(value or "").lower(),
                ).strip()
                if normalized_value:
                    listing_identifiers.append(normalized_value)

        kept_lines = []
        for line in reply.splitlines():
            stripped = line.strip()
            normalized_line = re.sub(
                r"[^a-z0-9]+",
                " ",
                stripped.lower(),
            ).strip()
            is_list_item = bool(re.match(r"^(?:[-*•]|\d+[.)])\s*", stripped))
            repeats_card = is_list_item and any(
                identifier in normalized_line
                for identifier in listing_identifiers
            )
            if not repeats_card:
                kept_lines.append(line)

        cleaned = "\n".join(kept_lines).strip()
        return cleaned or "Here are the matches I found."

    @staticmethod
    def _warning_filter_name(warnings: list[str]) -> str | None:
        """Extract one useful filter label without exposing internal diagnostics."""
        if not warnings:
            return None

        warning = warnings[0]
        patterns = (
            r"option matched:\s*(.+)$",
            r"choices for '[^']+' were unavailable:\s*(.+)$",
            r"Featured item '([^']+)'",
            r"Copart filter '([^']+)'",
            r"Copart range '([^']+)'",
            r"Copart option '([^']+)'",
        )
        for pattern in patterns:
            match = re.search(pattern, warning, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        if "ZIP-code proximity" in warning:
            return "ZIP-code proximity"
        return None

    @staticmethod
    def _build_tools() -> list[dict]:
        search_schema = copy.deepcopy(VehicleFilterConstraints.model_json_schema())
        search_schema["required"] = []
        search_schema["properties"].update({
            "search_id": {
                "type": "string",
                "description": "Saved search identifier for more results or refinements.",
            },
            "clear_filters": {
                "type": "array",
                "items": {"type": "string"},
            },
            "refresh": {"type": "boolean", "default": False},
        })
        detail_schema = {
            "type": "object",
            "properties": {
                "lot_id_or_url": {
                    "type": "string",
                    "description": "Copart lot number or Copart lot URL.",
                }
            },
            "required": ["lot_id_or_url"],
            "additionalProperties": False,
        }
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_copart_vehicles",
                    "description": "Search and refine Copart vehicle inventory.",
                    "parameters": search_schema,
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_copart_vehicle_details",
                    "description": "Get details and images for one Copart lot.",
                    "parameters": detail_schema,
                },
            },
        ]
