import asyncio
import os
import datetime
import hashlib
import json
import re
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from dotenv import load_dotenv
from backend.core.paths import PROJECT_ROOT
from backend.copart.browser import BrowserEngine
from backend.copart.models import (
    GENERIC_VEHICLE_TYPE_TERMS,
    VehicleFilterConstraints,
)

# Load environment configuration
load_dotenv()

LOG_FILE = str(PROJECT_ROOT / "debug.log")

def log_debug(msg: str):
    try:
        max_bytes = int(os.getenv("DEBUG_LOG_MAX_BYTES", "2000000"))
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) >= max_bytes:
            os.replace(LOG_FILE, f"{LOG_FILE}.1")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [Server] {msg}\n")
    except Exception:
        pass

# Instantiate the Copart browser adapter used by the search application service.
engine = BrowserEngine(log_callback=log_debug)
log_debug("Copart search service initialized with BrowserEngine")


@dataclass
class SearchSnapshot:
    search_id: str
    cache_key: str
    created_at: float
    query: str
    base_constraints: dict
    vehicles: list[dict]
    source_count_scanned: int
    source_has_more: bool
    filter_application: dict
    source_constraints: dict
    source_filter_application: dict
    pages_scanned: int
    session_id: str
    match_status: str = "exact"
    notice: Optional[str] = None
    filter_warnings: list[str] = field(default_factory=list)
    shown_vehicle_keys: set[str] = field(default_factory=set)


SEARCH_CACHE_TTL_SECONDS = max(
    1,
    int(os.getenv("SEARCH_CACHE_TTL_SECONDS", "600")),
)
_search_cache: dict[str, SearchSnapshot] = {}
_search_cache_by_id: dict[str, SearchSnapshot] = {}
_search_cache_lock = asyncio.Lock()
_browser_lock = asyncio.Lock()
MAX_CACHE_ENTRIES = max(10, int(os.getenv("SEARCH_CACHE_MAX_ENTRIES", "200")))


def _search_cache_key(
    constraints: VehicleFilterConstraints,
    session_id: str,
) -> tuple[str, dict]:
    """Build a stable key excluding display pagination fields."""
    values = constraints.model_dump(
        mode="json",
        exclude={"offset", "max_results"},
        exclude_none=True,
        exclude_defaults=True,
    )
    # Legacy convenience fields are already normalized into canonical lists.
    for legacy_key in ("title_type", "run_and_drive", "buy_it_now", "pure_sale"):
        values.pop(legacy_key, None)

    def normalize(value):
        if isinstance(value, str):
            return " ".join(value.lower().split())
        if isinstance(value, list):
            return sorted((normalize(item) for item in value), key=str)
        if isinstance(value, dict):
            return {
                key: normalize(item)
                for key, item in sorted(value.items())
            }
        return value

    canonical_values = normalize(values)
    encoded = json.dumps(
        {"session_id": session_id, "constraints": canonical_values},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), values


def _snapshot_response(
    snapshot: SearchSnapshot,
    constraints: VehicleFilterConstraints,
    *,
    cache_hit: bool,
    browser_used: bool,
) -> dict:
    start = constraints.offset
    end = min(start + constraints.max_results, len(snapshot.vehicles))
    vehicles = [
        {
            **vehicle,
            "current_bid": vehicle.get("current_bid") or "Not available",
        }
        for vehicle in snapshot.vehicles[start:end]
    ]
    has_cached_more = end < len(snapshot.vehicles)
    has_more = has_cached_more or snapshot.source_has_more
    age_seconds = max(0, int(time.time() - snapshot.created_at))
    newly_shown = []
    for vehicle in vehicles:
        vehicle_key = vehicle.get("lot_number") or vehicle.get("link")
        if vehicle_key and vehicle_key not in snapshot.shown_vehicle_keys:
            snapshot.shown_vehicle_keys.add(vehicle_key)
            newly_shown.append(vehicle_key)

    return {
        "query": snapshot.query,
        "applied_constraints": constraints.model_dump(exclude_none=True),
        "active_filters": snapshot.base_constraints,
        "search_id": snapshot.search_id,
        "cache_hit": cache_hit,
        "browser_used": browser_used,
        "result_source": (
            "cache_extended" if cache_hit and browser_used
            else "cache" if cache_hit
            else "live_search"
        ),
        "cache_age_seconds": age_seconds,
        "cache_ttl_seconds": SEARCH_CACHE_TTL_SECONDS,
        "cached_count": len(snapshot.vehicles),
        "source_count_scanned": snapshot.source_count_scanned,
        "source_has_more": snapshot.source_has_more,
        "filter_application": snapshot.filter_application,
        "source_filter_application": snapshot.source_filter_application,
        "filter_warnings": snapshot.filter_warnings,
        "match_status": snapshot.match_status,
        "notice": snapshot.notice,
        "offset": start,
        "next_offset": end if has_more else None,
        "count_returned": len(vehicles),
        "has_more": has_more,
        "has_cached_more": has_cached_more,
        "pages_scanned": snapshot.pages_scanned,
        "shown_count": len(snapshot.shown_vehicle_keys),
        "newly_shown_lot_ids": newly_shown,
        "vehicles": vehicles,
    }


async def _get_cached_snapshot(cache_key: str) -> Optional[SearchSnapshot]:
    now = time.time()
    async with _search_cache_lock:
        expired = [
            key
            for key, snapshot in _search_cache.items()
            if now - snapshot.created_at >= SEARCH_CACHE_TTL_SECONDS
        ]
        for key in expired:
            expired_snapshot = _search_cache.pop(key)
            _search_cache_by_id.pop(expired_snapshot.search_id, None)
        return _search_cache.get(cache_key)


async def _get_snapshot_by_id(
    search_id: str,
    session_id: str,
) -> Optional[SearchSnapshot]:
    await _get_cached_snapshot("__prune_only__")
    async with _search_cache_lock:
        snapshot = _search_cache_by_id.get(search_id)
        if snapshot and snapshot.session_id == session_id:
            return snapshot
        return None


async def _get_cached_listing_image(
    session_id: str,
    lot_id_or_url: str,
) -> str:
    """Find a previously shown listing image for immediate detail rendering."""
    await _get_cached_snapshot("__prune_only__")
    lot_text = str(lot_id_or_url).strip()
    lot_match = lot_text if lot_text.isdigit() else ""
    if not lot_match:
        url_lot_match = re.search(r"/lot/(\d{6,10})", lot_text, re.IGNORECASE)
        lot_match = url_lot_match.group(1) if url_lot_match else ""
    async with _search_cache_lock:
        snapshots = sorted(
            (
                snapshot
                for snapshot in _search_cache_by_id.values()
                if snapshot.session_id == session_id
            ),
            key=lambda snapshot: snapshot.created_at,
            reverse=True,
        )
        for snapshot in snapshots:
            for vehicle in snapshot.vehicles:
                vehicle_lot = str(vehicle.get("lot_number") or "")
                vehicle_link = str(vehicle.get("link") or "")
                if (
                    lot_match
                    and (
                        vehicle_lot == lot_match
                        or f"/lot/{lot_match}" in vehicle_link
                    )
                ):
                    return str(vehicle.get("image_url") or "")
    return ""


async def _store_snapshot(snapshot: SearchSnapshot) -> None:
    async with _search_cache_lock:
        previous = _search_cache.get(snapshot.cache_key)
        if previous:
            _search_cache_by_id.pop(previous.search_id, None)
        _search_cache[snapshot.cache_key] = snapshot
        _search_cache_by_id[snapshot.search_id] = snapshot
        if len(_search_cache) > MAX_CACHE_ENTRIES:
            oldest = min(_search_cache.values(), key=lambda item: item.created_at)
            _search_cache.pop(oldest.cache_key, None)
            _search_cache_by_id.pop(oldest.search_id, None)


def _filter_application_warnings(
    report: dict,
    constraints: Optional[VehicleFilterConstraints] = None,
    vehicles: Optional[list[dict]] = None,
) -> list[str]:
    """Turn browser adapter failures into user-facing, non-fatal warnings."""
    warnings = []
    vehicles = vehicles or []

    def normalized(value) -> str:
        return " ".join(
            "".join(character if character.isalnum() else " " for character in str(value).lower()).split()
        )

    def every_requested_value_is_present(requested, field_name) -> bool:
        if not requested or not vehicles:
            return False
        actual_values = [normalized(vehicle.get(field_name, "")) for vehicle in vehicles]
        def matches(value, actual) -> bool:
            normalized_value = normalized(value)
            if f" {normalized_value} " in f" {actual} ":
                return True
            compact_value = "".join(character for character in normalized_value if character.isalnum())
            compact_actual = "".join(character for character in actual if character.isalnum())
            return len(compact_value) >= 4 and compact_value in compact_actual

        return all(any(matches(value, actual) for actual in actual_values) for value in requested)

    def every_requested_value_is_in_query(requested) -> bool:
        if constraints is None or not requested or not vehicles:
            return False
        normalized_query = f" {normalized(constraints.query)} "
        return all(
            f" {normalized(value)} " in normalized_query
            for value in requested
            if normalized(value)
        )

    def facet_was_verified_locally(facet: str) -> bool:
        if constraints is None or not vehicles:
            return False
        if facet == "Make":
            return every_requested_value_is_present(constraints.makes, "title")
        if facet == "Model":
            return every_requested_value_is_present(constraints.models, "title")
        if facet == "Vehicle type":
            # When the type is also the Copart free-text query (for example,
            # SUV), the returned inventory already came from that search.
            # A duplicate sidebar option may not exist and should not turn a
            # successful search into a false partial match.
            return every_requested_value_is_in_query(constraints.vehicle_types)
        if facet == "Vehicle title type":
            return every_requested_value_is_present(
                constraints.title_types,
                "title_status",
            )
        if facet == "Damage Type" and constraints.damage:
            return every_requested_value_is_present([constraints.damage], "damage")
        if facet == "Location" and constraints.state and not constraints.locations:
            prefix = f"{constraints.state.upper()} -"
            return all(
                (vehicle.get("yard_location") or "").upper().startswith(prefix)
                for vehicle in vehicles
            )
        return False

    for featured, status in report.get("featured_items", {}).items():
        if status not in {"selected", "already_selected"}:
            warnings.append(f"Featured item '{featured}' was not available")

    for facet, result in report.get("facets", {}).items():
        if not isinstance(result, dict):
            continue
        if facet_was_verified_locally(facet):
            continue
        status = result.get("status")
        if status in {"facet_not_found", "scope_not_found"}:
            warnings.append(f"Copart filter '{facet}' could not be opened")
        elif status == "option_not_found":
            requested = result.get("requested") or []
            detail = ", ".join(str(value) for value in requested)
            warnings.append(f"No available '{facet}' option matched: {detail}")
        elif result.get("unmatched"):
            detail = ", ".join(str(value) for value in result["unmatched"])
            warnings.append(
                f"Some OR choices for '{facet}' were unavailable: {detail}"
            )

    for range_name, status in report.get("ranges", {}).items():
        if isinstance(status, str):
            if constraints is not None and vehicles and range_name in {"Year", "Odometer"}:
                # These two ranges are deterministically checked again by the
                # browser engine before records reach the server.
                continue
            warnings.append(f"Copart range '{range_name}' was not applied ({status})")
    for toggle, status in report.get("toggles", {}).items():
        if status not in {"selected", "already_selected"}:
            warnings.append(f"Copart option '{toggle}' was not applied")
    proximity = report.get("proximity")
    if isinstance(proximity, dict) and proximity.get("status") != "applied":
        warnings.append("ZIP-code proximity could not be applied")
    return warnings


def _has_search_filters(constraints: VehicleFilterConstraints) -> bool:
    values = constraints.model_dump(
        exclude={"query", "offset", "max_results"},
        exclude_none=True,
        exclude_defaults=True,
    )
    return bool(values)


def _source_values(constraints: VehicleFilterConstraints) -> dict:
    return constraints.model_dump(
        mode="json",
        exclude={"offset", "max_results"},
        exclude_none=True,
        exclude_defaults=True,
    )


async def _browser_search(
    constraints: VehicleFilterConstraints,
    *,
    scan_additional_pages: bool,
    max_source_pages: Optional[int] = None,
) -> dict:
    """Serialize access to the one persistent Copart Chrome profile."""
    async with _browser_lock:
        return await engine.search_and_extract(
            constraints,
            scan_additional_pages=scan_additional_pages,
            max_source_pages=max_source_pages,
        )


async def _extend_snapshot(
    snapshot: SearchSnapshot,
    constraints: VehicleFilterConstraints,
) -> None:
    """Re-run the source search and scan far enough to append the next page."""
    requested_end = constraints.offset + constraints.max_results
    target_count = min(
        max(
            len(snapshot.vehicles) + constraints.max_results,
            requested_end + constraints.max_results,
        ),
        max(50, int(os.getenv("COPART_MAX_CACHED_RESULTS", "500"))),
    )
    continuation_batch = max(
        1,
        int(os.getenv("COPART_CONTINUATION_PAGE_BATCH", "15")),
    )
    max_total_pages = max(
        continuation_batch,
        int(os.getenv("COPART_MAX_TOTAL_SEARCH_PAGES", "60")),
    )
    max_source_pages = min(
        max(snapshot.pages_scanned, 1) + continuation_batch,
        max_total_pages,
    )
    source_constraints = VehicleFilterConstraints(**snapshot.source_constraints)
    browser_constraints = source_constraints.model_copy(
        update={"offset": 0, "max_results": target_count}
    )
    browser_result = await _browser_search(
        browser_constraints,
        scan_additional_pages=True,
        max_source_pages=max_source_pages,
    )
    expanded = browser_result.get("vehicles", [])
    previous_count = len(snapshot.vehicles)
    if len(expanded) > previous_count:
        snapshot.vehicles = expanded
        snapshot.created_at = time.time()
    snapshot.source_count_scanned = browser_result.get(
        "source_count_scanned", snapshot.source_count_scanned
    )
    snapshot.pages_scanned = browser_result.get(
        "pages_scanned", snapshot.pages_scanned
    )
    snapshot.source_filter_application = browser_result.get(
        "filter_application", snapshot.source_filter_application
    )
    source_has_more = bool(browser_result.get("source_has_more", False))
    snapshot.source_has_more = source_has_more and snapshot.pages_scanned < max_total_pages

async def search_copart_vehicles(
    query: Optional[str] = None,
    search_id: Optional[str] = None,
    session_id: str = "default",
    title_type: Optional[str] = None,
    run_and_drive: Optional[bool] = None,
    buy_it_now: Optional[bool] = None,
    pure_sale: Optional[bool] = None,
    min_year: Optional[int] = None,
    max_year: Optional[int] = None,
    state: Optional[str] = None,
    damage: Optional[str] = None,
    min_odometer: Optional[int] = None,
    max_odometer: Optional[int] = None,
    featured_items: Optional[List[str]] = None,
    title_types: Optional[List[str]] = None,
    condition_types: Optional[List[str]] = None,
    vehicle_types: Optional[List[str]] = None,
    makes: Optional[List[str]] = None,
    models: Optional[List[str]] = None,
    engine_types: Optional[List[str]] = None,
    transmissions: Optional[List[str]] = None,
    fuel_types: Optional[List[str]] = None,
    drive_trains: Optional[List[str]] = None,
    cylinders: Optional[List[str]] = None,
    auction_names: Optional[List[str]] = None,
    locations: Optional[List[str]] = None,
    body_styles: Optional[List[str]] = None,
    sale_lights: Optional[List[str]] = None,
    min_autograde: Optional[float] = None,
    max_autograde: Optional[float] = None,
    zip_code: Optional[str] = None,
    radius_miles: Optional[int] = None,
    sale_date_from: Optional[str] = None,
    sale_date_to: Optional[str] = None,
    newly_added: Optional[str] = None,
    lots_anyone_can_bid_on: Optional[bool] = None,
    wholesale_only: Optional[bool] = None,
    exclude_upcoming_auctions: Optional[bool] = None,
    exclude_purple_wave: Optional[bool] = None,
    additional_facets: Optional[Dict[str, List[str]]] = None,
    include_terms: Optional[List[str]] = None,
    exclude_terms: Optional[List[str]] = None,
    clear_filters: Optional[List[str]] = None,
    max_results: int = 4,
    offset: int = 0,
    refresh: bool = False,
) -> dict:
    """
    Search Copart's vehicle auction inventory with filters. The first call
    caches matching vehicles from Copart's first result page. Follow-ups use
    saved records first, then automatically extend the snapshot into later
    Copart pages. Set refresh to true to bypass the cache.
    """
    log_debug(
        f"search_copart_vehicles called: query='{query}', search_id='{search_id}', "
        f"state='{state}', min_year={min_year}, max_year={max_year}"
    )
    try:
        base_values = {}
        if search_id:
            prior_snapshot = await _get_snapshot_by_id(search_id, session_id)
            if not prior_snapshot:
                raise ValueError(
                    "search_id is missing or expired; provide query and filters for a new search"
                )
            base_values.update(prior_snapshot.base_constraints)

        updates = {
            "query": query,
            "title_type": title_type,
            "run_and_drive": run_and_drive,
            "buy_it_now": buy_it_now,
            "pure_sale": pure_sale,
            "min_year": min_year,
            "max_year": max_year,
            "state": state,
            "damage": damage,
            "min_odometer": min_odometer,
            "max_odometer": max_odometer,
            "featured_items": featured_items,
            "title_types": title_types,
            "condition_types": condition_types,
            "vehicle_types": vehicle_types,
            "makes": makes,
            "models": models,
            "engine_types": engine_types,
            "transmissions": transmissions,
            "fuel_types": fuel_types,
            "drive_trains": drive_trains,
            "cylinders": cylinders,
            "auction_names": auction_names,
            "locations": locations,
            "body_styles": body_styles,
            "sale_lights": sale_lights,
            "min_autograde": min_autograde,
            "max_autograde": max_autograde,
            "zip_code": zip_code,
            "radius_miles": radius_miles,
            "sale_date_from": sale_date_from,
            "sale_date_to": sale_date_to,
            "newly_added": newly_added,
            "lots_anyone_can_bid_on": lots_anyone_can_bid_on,
            "wholesale_only": wholesale_only,
            "exclude_upcoming_auctions": exclude_upcoming_auctions,
            "exclude_purple_wave": exclude_purple_wave,
            "additional_facets": additional_facets,
            "include_terms": include_terms,
            "exclude_terms": exclude_terms,
        }

        # Legacy convenience booleans are normalized into featured_items by
        # the model. Explicit false values and clear operations must remove
        # that canonical value as well, otherwise a refinement appears to work
        # while the previous filter remains active.
        legacy_feature_names = {
            "run_and_drive": "Run and Drive",
            "buy_it_now": "Buy It Now",
            "pure_sale": "Pure Sale Items",
        }
        for legacy_name, featured_name in legacy_feature_names.items():
            if updates[legacy_name] is False:
                base_values["featured_items"] = [
                    value
                    for value in base_values.get("featured_items", [])
                    if value != featured_name
                ]

        # A singular title_type refinement replaces the previous singular
        # choice unless the caller deliberately supplies title_types as an OR
        # list in the same request.
        if title_type is not None and title_types is None:
            base_values["title_types"] = [title_type]

        base_values.update(
            {key: value for key, value in updates.items() if value is not None}
        )
        if base_values.get("vehicle_types"):
            base_values["vehicle_types"] = [
                value
                for value in base_values["vehicle_types"]
                if not (
                    isinstance(value, str)
                    and value.strip().lower() in GENERIC_VEHICLE_TYPE_TERMS
                )
            ]
        for legacy_name, featured_name in legacy_feature_names.items():
            if updates[legacy_name] is False:
                base_values["featured_items"] = [
                    value
                    for value in base_values.get("featured_items", [])
                    if value != featured_name
                ]
        valid_filter_names = set(VehicleFilterConstraints.model_fields) - {
            "max_results",
            "offset",
        }
        unknown_clear_filters = sorted(
            set(clear_filters or []) - valid_filter_names
        )
        if unknown_clear_filters:
            raise ValueError(
                "Unknown clear_filters value(s): "
                + ", ".join(unknown_clear_filters)
            )
        for filter_name in clear_filters or []:
            base_values.pop(filter_name, None)
            featured_name = legacy_feature_names.get(filter_name)
            if featured_name:
                base_values["featured_items"] = [
                    value
                    for value in base_values.get("featured_items", [])
                    if value != featured_name
                ]
            if filter_name == "title_type":
                base_values.pop("title_types", None)

        if not base_values.get("query"):
            # Tool-calling models often express make/model entirely through
            # their dedicated facets. Copart still needs text in its search
            # box, so derive the least-surprising query instead of rejecting
            # an otherwise valid request.
            makes_value = base_values.get("makes") or []
            models_value = base_values.get("models") or []
            vehicle_types_value = base_values.get("vehicle_types") or []
            if len(makes_value) <= 1 and len(models_value) <= 1:
                query_parts = [
                    str(value)
                    for value in (*makes_value, *models_value)
                    if value
                ]
            elif vehicle_types_value:
                # For a compound request, a shared vehicle type is a safer
                # broad query than silently biasing the search to the first make.
                query_parts = [str(vehicle_types_value[0])]
            else:
                query_parts = []
            if not query_parts and vehicle_types_value:
                query_parts = [str(vehicle_types_value[0])]
            if not query_parts:
                # Broad natural-language requests can consist entirely of
                # structured criteria, such as "hybrids with Buy It Now".
                # Use a neutral inventory query and let the requested Copart
                # facets provide the actual narrowing.
                query_parts = ["vehicles"]
            base_values["query"] = " ".join(query_parts)

        base_values["max_results"] = max_results
        base_values["offset"] = offset
        constraints = VehicleFilterConstraints(**base_values)
        powertrain_terms = [
            search_term
            for featured_item, search_term in (
                ("Hybrid", "hybrid"),
                ("Electric Vehicles", "electric"),
            )
            if featured_item in constraints.featured_items
        ]
        # Reinforce one requested powertrain through Copart's text search.
        # When both are requested, keep the Featured Items' OR behavior rather
        # than turning "hybrid electric" into an accidental AND requirement.
        if len(powertrain_terms) == 1:
            powertrain_term = powertrain_terms[0]
            query = constraints.query.strip()
            if query.lower() == "vehicles":
                query = powertrain_term
            elif powertrain_term not in query.lower().split():
                query = f"{query} {powertrain_term}"
            constraints = constraints.model_copy(update={"query": query})
        log_debug(f"Constraints validated: state={constraints.state}")
        cache_key, base_constraints = _search_cache_key(constraints, session_id)

        if not refresh:
            snapshot = await _get_cached_snapshot(cache_key)
            if snapshot:
                browser_used = False
                if (
                    constraints.offset >= len(snapshot.vehicles)
                    and snapshot.source_has_more
                ):
                    await _extend_snapshot(snapshot, constraints)
                    browser_used = True
                result = _snapshot_response(
                    snapshot,
                    constraints,
                    cache_hit=True,
                    browser_used=browser_used,
                )
                log_debug(
                    f"Search cache hit: id={snapshot.search_id}, "
                    f"offset={constraints.offset}, returned={len(result['vehicles'])}"
                )
                return result

        browser_constraints = constraints.model_copy(
            update={"offset": 0, "max_results": 50}
        )
        browser_result = await _browser_search(
            browser_constraints,
            scan_additional_pages=False,
        )
        exact_filter_application = browser_result.get("filter_application", {})
        filter_warnings = _filter_application_warnings(
            exact_filter_application,
            constraints,
            browser_result.get("vehicles", []),
        )
        source_constraints = _source_values(constraints)
        source_result = browser_result
        match_status = "exact"
        notice = None

        if browser_result.get("vehicles"):
            if filter_warnings:
                match_status = "partial_matches"
                notice = (
                    "Some requested filter choices were unavailable. Results from "
                    "the remaining successfully applied choices are shown; see "
                    "filter_warnings."
                )
        elif _has_search_filters(constraints):
            # The full AND combination had no results. Relax optional auction
            # facets, but keep vehicle identity, year, mileage, location, and
            # explicit text exclusions. These are hard user requirements and
            # must not disappear merely because results are labelled "close".
            relaxed_constraints = VehicleFilterConstraints(
                query=constraints.query,
                makes=constraints.makes,
                models=constraints.models,
                min_year=constraints.min_year,
                max_year=constraints.max_year,
                state=constraints.state,
                locations=constraints.locations,
                min_odometer=constraints.min_odometer,
                max_odometer=constraints.max_odometer,
                include_terms=constraints.include_terms,
                exclude_terms=constraints.exclude_terms,
                max_results=50,
            )
            source_result = await _browser_search(
                relaxed_constraints,
                scan_additional_pages=False,
            )
            source_constraints = _source_values(relaxed_constraints)
            if source_result.get("vehicles"):
                match_status = "close_matches"
                notice = (
                    "No vehicles matched every optional filter. These alternatives "
                    "still satisfy the requested vehicle, year, mileage, and location "
                    "requirements."
                )
            else:
                match_status = "no_matches"
                notice = "No exact or close vehicle matches were found."
        elif not browser_result.get("vehicles"):
            match_status = "no_matches"
            notice = "No vehicles matched the search query."

        snapshot = SearchSnapshot(
            search_id=uuid.uuid4().hex[:12],
            cache_key=cache_key,
            created_at=time.time(),
            query=constraints.query,
            base_constraints=base_constraints,
            vehicles=source_result.get("vehicles", []),
            source_count_scanned=source_result.get("source_count_scanned", 0),
            source_has_more=source_result.get("source_has_more", False),
            filter_application=exact_filter_application,
            source_constraints=source_constraints,
            source_filter_application=source_result.get("filter_application", {}),
            pages_scanned=source_result.get("pages_scanned", 1),
            session_id=session_id,
            match_status=match_status,
            notice=notice,
            filter_warnings=filter_warnings,
        )
        await _store_snapshot(snapshot)
        result = _snapshot_response(
            snapshot,
            constraints,
            cache_hit=False,
            browser_used=True,
        )
        log_debug(
            f"Fresh search cached: id={snapshot.search_id}, "
            f"source_rows={snapshot.source_count_scanned}, "
            f"matches={len(snapshot.vehicles)}, returned={len(result['vehicles'])}"
        )
        return result
    except Exception as e:
        err_msg = f"{type(e).__name__}: {str(e)}"
        log_debug(f"ERROR in search_copart_vehicles: {err_msg}\n{traceback.format_exc()}")
        return {
            "error": err_msg,
            "vehicles": [],
            "count_returned": 0
        }

async def get_copart_vehicle_details(
    lot_id_or_url: str,
    session_id: str = "default",
) -> dict:
    """
    Deep-dive inspection on a single Copart vehicle.
    Takes an 8-digit Lot Number (e.g. '72087666') or direct Copart lot URL.
    Returns VIN, exact auction date/time, condition, and full 10-25 HD photo gallery.
    """
    log_debug(f"get_copart_vehicle_details called: lot={lot_id_or_url}")
    try:
        cached_image = await _get_cached_listing_image(session_id, lot_id_or_url)
        async with _browser_lock:
            result = await engine.get_vehicle_details(lot_id_or_url)
        gallery = list(result.get("gallery_photos") or [])
        primary_image = result.get("primary_image_url") or cached_image
        if primary_image and primary_image not in gallery:
            gallery.insert(0, primary_image)
        result["primary_image_url"] = primary_image
        result["gallery_photos"] = gallery
        result["image_status"] = "ready" if primary_image else "unavailable"
        result["image_loading"] = {
            "eager": [primary_image] if primary_image else [],
            "lazy": [image for image in gallery if image != primary_image],
        }
        log_debug(f"Inspection successful for {lot_id_or_url}")
        return result
    except Exception as e:
        err_msg = f"{type(e).__name__}: {str(e)}"
        log_debug(f"ERROR in get_copart_vehicle_details: {err_msg}\n{traceback.format_exc()}")
        return {
            "error": err_msg,
            "vehicle_title": "Error inspecting vehicle lot",
            "gallery_photos": []
        }


