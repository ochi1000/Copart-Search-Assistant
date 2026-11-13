import unittest
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from playwright.async_api import async_playwright

from backend.copart import search as server
from backend.copart.browser import BrowserEngine
from backend.copart.models import VehicleFilterConstraints


class FakeEngine:
    def __init__(self):
        self.calls = []

    async def search_and_extract(
        self,
        constraints,
        *,
        scan_additional_pages=True,
        max_source_pages=None,
    ):
        self.calls.append((constraints, scan_additional_pages))
        vehicle_count = 3 if scan_additional_pages else 1
        return {
            "vehicles": [
                {
                    "title": f"2024 TOYOTA CAMRY LE {index}",
                    "lot_number": f"1234567{index}",
                    "title_status": "Clean Title",
                    "damage": "Front End Damage",
                    "odometer": "50000 (ACTUAL)",
                    "odometer_miles": 50000,
                    "yard_location": "TX - DALLAS",
                    "current_bid": "$100.00",
                    "buy_it_now_price": "",
                    "link": f"https://example.test/lot/1234567{index}",
                    "image_url": f"https://example.test/vehicle-{index}.jpg",
                }
                for index in range(vehicle_count)
            ],
            "source_count_scanned": 100 if scan_additional_pages else 50,
            "source_has_more": not scan_additional_pages,
            "pages_scanned": 2 if scan_additional_pages else 1,
            "filter_application": {"status": "fake"},
        }


class CloseMatchEngine:
    def __init__(self):
        self.calls = []

    async def search_and_extract(
        self,
        constraints,
        *,
        scan_additional_pages=True,
        max_source_pages=None,
    ):
        self.calls.append((constraints, scan_additional_pages))
        vehicles = []
        if not constraints.title_types:
            vehicles = [{
                "title": "2023 TOYOTA CAMRY LE",
                "lot_number": "87654321",
                "title_status": "Salvage Title",
                "damage": "Rear End Damage",
                "odometer": "70000 (ACTUAL)",
                "odometer_miles": 70000,
                "yard_location": "TX - DALLAS",
                "current_bid": "$200.00",
                "buy_it_now_price": "",
                "link": "https://example.test/lot/87654321",
                "image_url": "",
            }]
        return {
            "vehicles": vehicles,
            "source_count_scanned": 50,
            "source_has_more": False,
            "pages_scanned": 1,
            "filter_application": {},
        }


class PartialFilterEngine(FakeEngine):
    async def search_and_extract(
        self,
        constraints,
        *,
        scan_additional_pages=True,
        max_source_pages=None,
    ):
        result = await super().search_and_extract(
            constraints,
            scan_additional_pages=scan_additional_pages,
            max_source_pages=max_source_pages,
        )
        result["filter_application"] = {
            "facets": {
                "Fuel type": {
                    "status": "applied",
                    "requested": ["Hybrid", "Electric"],
                    "matched": ["hybrid"],
                    "unmatched": ["Electric"],
                }
            }
        }
        return result


class DetailEngine:
    async def get_vehicle_details(self, lot_id_or_url):
        return {
            "lot_url": f"https://www.copart.com/lot/{lot_id_or_url}",
            "vehicle_title": "2024 TOYOTA CAMRY LE",
            "gallery_photos": [],
            "photo_count": 0,
        }


class FilterModelTests(unittest.TestCase):
    def test_feature_aliases_and_legacy_fields_are_canonical(self):
        constraints = VehicleFilterConstraints(
            query="cars",
            featured_items=["ev", "repo"],
            run_and_drive=True,
            title_type="Clean Title",
        )
        self.assertEqual(
            constraints.featured_items,
            ["Electric Vehicles", "Bank / Repossessed", "Run and Drive"],
        )
        self.assertEqual(constraints.title_types, ["Clean Title"])

    def test_hybrid_fuel_value_uses_copart_featured_item(self):
        constraints = VehicleFilterConstraints(
            query="vehicles",
            fuel_types=["Hybrid"],
            buy_it_now=True,
        )
        self.assertEqual(constraints.fuel_types, [])
        self.assertIn("Hybrid", constraints.featured_items)
        self.assertIn("Buy It Now", constraints.featured_items)

    def test_hybrid_vehicles_alias_uses_copart_featured_item(self):
        constraints = VehicleFilterConstraints(
            query="vehicles",
            featured_items=["Hybrid Vehicles"],
        )
        self.assertEqual(constraints.featured_items, ["Hybrid"])

    def test_electric_fuel_value_uses_copart_featured_item(self):
        constraints = VehicleFilterConstraints(
            query="vehicles",
            fuel_types=["Electric"],
        )
        self.assertEqual(constraints.fuel_types, [])
        self.assertIn("Electric Vehicles", constraints.featured_items)

    def test_generic_car_word_is_not_a_vehicle_type_filter(self):
        constraints = VehicleFilterConstraints(
            query="vehicles",
            vehicle_types=["Car", "SUV"],
        )
        self.assertEqual(constraints.vehicle_types, ["SUV"])

    def test_invalid_range_is_rejected(self):
        with self.assertRaises(ValueError):
            VehicleFilterConstraints(query="cars", min_year=2025, max_year=2022)

    def test_unknown_state_is_rejected(self):
        with self.assertRaises(ValueError):
            VehicleFilterConstraints(query="cars", state="banana")

    def test_include_and_exclude_terms_use_or_and_not_semantics(self):
        constraints = VehicleFilterConstraints(
            query="cars",
            include_terms=["Hybrid", "Electric"],
            exclude_terms=["Flood"],
        )
        items = [
            {"title": "Hybrid Camry", "raw_text": "Hybrid Front End"},
            {"title": "Electric Leaf", "raw_text": "Electric Flood Damage"},
            {"title": "Gas Camry", "raw_text": "Gas Front End"},
        ]
        filtered = BrowserEngine._filter_items(items, constraints)
        self.assertEqual([item["title"] for item in filtered], ["Hybrid Camry"])

    def test_make_and_model_are_verified_against_extracted_titles(self):
        constraints = VehicleFilterConstraints(
            query="sedan",
            makes=["Toyota", "Lexus"],
            models=["Camry", "ES 350"],
        )
        items = [
            {"title": "2022 TOYOTA CAMRY SE"},
            {"title": "2022 LEXUS ES 350"},
            {"title": "2022 TOYOTA COROLLA LE"},
        ]
        filtered = BrowserEngine._filter_items(items, constraints)
        self.assertEqual(len(filtered), 2)

        spaced_model = VehicleFilterConstraints(
            query="Lexus RX350",
            makes=["Lexus"],
            models=["RX350"],
            min_year=2020,
        )
        filtered = BrowserEngine._filter_items(
            [{"title": "2022 LEXUS RX 350 BASE"}],
            spaced_model,
        )
        self.assertEqual(len(filtered), 1)

    def test_locally_verified_filters_do_not_create_false_warnings(self):
        constraints = VehicleFilterConstraints(
            query="Toyota Camry",
            makes=["Toyota"],
            models=["Camry"],
            state="TX",
            min_year=2022,
        )
        report = {
            "facets": {
                "Make": {"status": "option_not_found", "requested": ["Toyota"]},
                "Model": {"status": "option_not_found", "requested": ["Camry"]},
                "Location": {"status": "facet_not_found", "requested": ["TX"]},
            },
            "ranges": {"Year": "inputs_not_found"},
        }
        vehicles = [{
            "title": "2024 TOYOTA CAMRY SE",
            "yard_location": "TX - DALLAS",
            "odometer_miles": 50000,
        }]
        warnings = server._filter_application_warnings(
            report,
            constraints,
            vehicles,
        )
        self.assertEqual(warnings, [])


class BrowserProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_imperva_error_is_recognized_as_hard_access_denial(self):
        body = SimpleNamespace(
            inner_text=AsyncMock(
                return_value=(
                    "Access denied Error 15. This request was blocked by "
                    "our security service. Powered by Imperva."
                )
            )
        )
        page = SimpleNamespace(locator=lambda _: body)

        self.assertTrue(await BrowserEngine._access_denied_present(page))

    def test_provider_diagnostics_redact_credentials(self):
        with patch.dict(
            os.environ,
            {"BROWSERLESS_TOKEN": "browser-secret"},
            clear=False,
        ):
            message = server._redact_sensitive(
                "connect wss://example.test?token=browser-secret&timeout=30000"
            )

        self.assertNotIn("browser-secret", message)
        self.assertIn("token=[redacted]", message)

    def test_browserless_connection_url_encodes_secrets_and_profile(self):
        with patch.dict(
            os.environ,
            {
                "BROWSER_PROVIDER": "browserless",
                "BROWSERLESS_TOKEN": "token+with/slash",
                "BROWSERLESS_PROFILE": "copart demo",
                "BROWSERLESS_ENDPOINT": "wss://production-sfo.browserless.io",
                "BROWSERLESS_SESSION_TIMEOUT_MS": "120000",
            },
            clear=False,
        ):
            browser = BrowserEngine()

        url = browser._browserless_ws_url()
        self.assertIn("token=token%2Bwith%2Fslash", url)
        self.assertIn("profile=copart+demo", url)
        self.assertIn("timeout=120000", url)

    async def test_browserless_live_url_is_interactive_and_short_lived(self):
        with patch.dict(
            os.environ,
            {
                "BROWSER_PROVIDER": "browserless",
                "BROWSERLESS_TOKEN": "test-token",
                "BROWSERLESS_LIVE_TIMEOUT_MS": "90000",
            },
            clear=False,
        ):
            browser = BrowserEngine()

        cdp = SimpleNamespace(
            send=AsyncMock(return_value={
                "liveURL": "https://browser.example/live/session",
                "liveURLId": "live-1",
                "timeout": 85000,
            }),
            detach=AsyncMock(),
        )
        context = SimpleNamespace(new_cdp_session=AsyncMock(return_value=cdp))
        page = SimpleNamespace(context=context)

        live_url, live_url_id, timeout_ms = (
            await browser._create_browserless_live_url(page)
        )

        self.assertEqual(live_url, "https://browser.example/live/session")
        self.assertEqual(live_url_id, "live-1")
        self.assertEqual(timeout_ms, 85000)
        command, options = cdp.send.await_args.args
        self.assertEqual(command, "Browserless.liveURL")
        self.assertTrue(options["interactable"])
        self.assertEqual(options["timeout"], 90000)
        self.assertEqual(options["instructions"]["layout"], "panel")
        cdp.detach.assert_awaited_once()

    def test_query_backed_vehicle_type_does_not_create_false_warning(self):
        constraints = VehicleFilterConstraints(
            query="SUV",
            vehicle_types=["SUV"],
            state="TX",
        )
        report = {
            "facets": {
                "Vehicle type": {
                    "status": "option_not_found",
                    "requested": ["SUV"],
                    "unmatched": ["SUV"],
                }
            }
        }
        vehicles = [{
            "title": "2023 FORD EXPLORER XLT",
            "yard_location": "TX - DALLAS",
        }]
        warnings = server._filter_application_warnings(
            report,
            constraints,
            vehicles,
        )
        self.assertEqual(warnings, [])

    def test_unconfirmed_separate_vehicle_type_still_warns(self):
        constraints = VehicleFilterConstraints(
            query="Toyota",
            vehicle_types=["SUV"],
        )
        report = {
            "facets": {
                "Vehicle type": {
                    "status": "option_not_found",
                    "requested": ["SUV"],
                    "unmatched": ["SUV"],
                }
            }
        }
        warnings = server._filter_application_warnings(
            report,
            constraints,
            [{"title": "2023 TOYOTA RAV4"}],
        )
        self.assertIn("SUV", warnings[0])


class ConversationStateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original_engine = server.engine
        self.fake = FakeEngine()
        server.engine = self.fake
        server._search_cache.clear()
        server._search_cache_by_id.clear()

    async def asyncTearDown(self):
        server.engine = self.original_engine
        server._search_cache.clear()
        server._search_cache_by_id.clear()

    async def test_more_refine_and_clear_preserve_conversation_state(self):
        first = await server.search_copart_vehicles(
            query="Toyota Camry",
            state="Texas",
            featured_items=["ev", "run & drive"],
            min_year=2022,
        )
        more = await server.search_copart_vehicles(
            search_id=first["search_id"],
            offset=1,
        )
        equivalent = await server.search_copart_vehicles(
            query="  toyota   camry ",
            state="TX",
            featured_items=["Run and Drive", "Electric Vehicles"],
            min_year=2022,
        )
        refined = await server.search_copart_vehicles(
            search_id=first["search_id"],
            max_odometer=100000,
        )
        cleared = await server.search_copart_vehicles(
            search_id=refined["search_id"],
            clear_filters=["state"],
        )

        self.assertFalse(first["cache_hit"])
        self.assertEqual(first["result_source"], "live_search")
        self.assertTrue(more["cache_hit"])
        self.assertEqual(more["result_source"], "cache_extended")
        self.assertTrue(equivalent["cache_hit"])
        self.assertEqual(equivalent["result_source"], "cache")
        self.assertEqual(equivalent["search_id"], first["search_id"])
        self.assertEqual(len(self.fake.calls), 4)
        self.assertEqual(more["pages_scanned"], 2)
        self.assertGreater(more["shown_count"], first["shown_count"])
        refined_constraints = self.fake.calls[2][0]
        self.assertEqual(refined_constraints.query, "Toyota Camry electric")
        self.assertEqual(refined_constraints.state, "TX")
        self.assertEqual(refined_constraints.min_year, 2022)
        self.assertEqual(refined_constraints.max_odometer, 100000)
        self.assertIsNone(self.fake.calls[3][0].state)
        self.assertNotEqual(cleared["search_id"], refined["search_id"])

    async def test_zero_exact_results_are_labelled_close_matches(self):
        server.engine = CloseMatchEngine()
        result = await server.search_copart_vehicles(
            query="Toyota Camry",
            state="TX",
            min_year=2022,
            title_types=["Clean Title"],
        )
        self.assertEqual(result["match_status"], "close_matches")
        self.assertIn("No vehicles matched", result["notice"])
        self.assertEqual(result["count_returned"], 1)
        self.assertEqual(len(server.engine.calls), 2)
        relaxed = server.engine.calls[1][0]
        self.assertEqual(relaxed.state, "TX")
        self.assertEqual(relaxed.min_year, 2022)
        self.assertEqual(relaxed.title_types, [])

    async def test_unavailable_or_choice_returns_partial_results_with_warning(self):
        server.engine = PartialFilterEngine()
        result = await server.search_copart_vehicles(
            query="Toyota Camry",
            fuel_types=["Hybrid", "Electric"],
        )
        self.assertEqual(result["match_status"], "partial_matches")
        self.assertIn("Electric", result["filter_warnings"][0])
        self.assertEqual(result["count_returned"], 1)

    async def test_cache_and_search_ids_are_scoped_to_session(self):
        first = await server.search_copart_vehicles(
            query="Toyota Camry",
            session_id="one",
        )
        second = await server.search_copart_vehicles(
            query="Toyota Camry",
            session_id="two",
        )
        foreign = await server.search_copart_vehicles(
            search_id=first["search_id"],
            session_id="two",
        )
        self.assertNotEqual(first["search_id"], second["search_id"])
        self.assertIn("missing or expired", foreign["error"])

    async def test_list_refinement_replaces_only_that_list(self):
        first = await server.search_copart_vehicles(
            query="Toyota Camry",
            state="TX",
            featured_items=["Electric Vehicles"],
        )
        await server.search_copart_vehicles(
            search_id=first["search_id"],
            featured_items=["Hybrid"],
        )
        refined = self.fake.calls[-1][0]
        self.assertEqual(refined.featured_items, ["Hybrid"])
        self.assertEqual(refined.state, "TX")

    async def test_query_is_derived_from_make_and_model_facets(self):
        result = await server.search_copart_vehicles(
            makes=["Toyota"],
            models=["Camry"],
            state="TX",
        )
        self.assertNotIn("error", result)
        self.assertEqual(self.fake.calls[0][0].query, "Toyota Camry")
        self.assertEqual(result["query"], "Toyota Camry")
        self.assertTrue(
            all(vehicle.get("current_bid") for vehicle in result["vehicles"])
        )

    async def test_missing_current_bid_is_returned_explicitly(self):
        class MissingBidEngine(FakeEngine):
            async def search_and_extract(self, *args, **kwargs):
                result = await super().search_and_extract(*args, **kwargs)
                result["vehicles"][0]["current_bid"] = ""
                return result

        server.engine = MissingBidEngine()
        result = await server.search_copart_vehicles(query="Toyota Camry")
        self.assertEqual(result["vehicles"][0]["current_bid"], "Not available")

    async def test_compound_make_search_uses_shared_vehicle_type_query(self):
        result = await server.search_copart_vehicles(
            makes=["Toyota", "Lexus"],
            vehicle_types=["Sedan"],
            min_year=2022,
        )
        self.assertNotIn("error", result)
        self.assertEqual(self.fake.calls[0][0].query, "Sedan")

    async def test_filter_only_search_uses_neutral_vehicle_query(self):
        result = await server.search_copart_vehicles(
            fuel_types=["Hybrid"],
            buy_it_now=True,
        )
        self.assertNotIn("error", result)
        self.assertEqual(self.fake.calls[0][0].query, "hybrid")
        self.assertEqual(self.fake.calls[0][0].fuel_types, [])
        self.assertIn("Hybrid", self.fake.calls[0][0].featured_items)
        self.assertIn("Buy It Now", self.fake.calls[0][0].featured_items)

    async def test_generic_car_type_does_not_become_a_copart_filter(self):
        result = await server.search_copart_vehicles(
            vehicle_types=["Car"],
            locations=["Texas", "Louisiana", "New York"],
            min_year=2015,
        )
        self.assertNotIn("error", result)
        self.assertEqual(self.fake.calls[0][0].query, "vehicles")
        self.assertEqual(self.fake.calls[0][0].vehicle_types, [])

    async def test_hybrid_is_appended_to_a_specific_vehicle_query(self):
        result = await server.search_copart_vehicles(
            query="Toyota Camry",
            fuel_types=["Hybrid"],
        )
        self.assertNotIn("error", result)
        self.assertEqual(self.fake.calls[0][0].query, "Toyota Camry hybrid")

    async def test_electric_search_uses_feature_and_text_query(self):
        result = await server.search_copart_vehicles(
            fuel_types=["Electric"],
            locations=["Shreveport", "LA", "FL"],
        )
        self.assertNotIn("error", result)
        constraints = self.fake.calls[0][0]
        self.assertEqual(constraints.query, "electric")
        self.assertEqual(constraints.fuel_types, [])
        self.assertIn("Electric Vehicles", constraints.featured_items)

    async def test_multiple_powertrains_keep_featured_item_or_semantics(self):
        result = await server.search_copart_vehicles(
            fuel_types=["Hybrid", "Electric"],
        )
        self.assertNotIn("error", result)
        constraints = self.fake.calls[0][0]
        self.assertEqual(constraints.query, "vehicles")
        self.assertEqual(
            constraints.featured_items,
            ["Hybrid", "Electric Vehicles"],
        )

    async def test_false_legacy_feature_removes_previous_canonical_filter(self):
        first = await server.search_copart_vehicles(
            query="Toyota Camry",
            run_and_drive=True,
        )
        await server.search_copart_vehicles(
            search_id=first["search_id"],
            run_and_drive=False,
        )
        refined = self.fake.calls[-1][0]
        self.assertFalse(refined.run_and_drive)
        self.assertNotIn("Run and Drive", refined.featured_items)

    async def test_clearing_legacy_title_type_clears_canonical_titles(self):
        first = await server.search_copart_vehicles(
            query="Toyota Camry",
            title_type="Clean Title",
        )
        await server.search_copart_vehicles(
            search_id=first["search_id"],
            clear_filters=["title_type"],
        )
        refined = self.fake.calls[-1][0]
        self.assertEqual(refined.title_types, [])

    async def test_vehicle_details_rejects_non_copart_urls(self):
        engine = BrowserEngine(headless=True)
        with self.assertRaises(ValueError):
            await engine.get_vehicle_details("https://example.com/lot/12345678")

    async def test_detail_uses_cached_listing_image_as_primary_fallback(self):
        first = await server.search_copart_vehicles(query="Toyota Camry")
        server.engine = DetailEngine()
        details = await server.get_copart_vehicle_details(
            first["vehicles"][0]["lot_number"],
        )
        self.assertEqual(
            details["primary_image_url"],
            "https://example.test/vehicle-0.jpg",
        )
        self.assertEqual(details["image_loading"]["eager"], [details["primary_image_url"]])


class BrowserFacetAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()
        self.engine = BrowserEngine(headless=False)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def test_feature_facets_and_range_are_applied_without_state_facet(self):
        await self.page.set_content(
            """
            <p-chip id="ev">Electric Vehicles</p-chip>
            <search-filter>
              <search-filter-header>Location</search-filter-header>
              <label><input id="tx-dallas" type="checkbox">TX - Dallas (12)</label>
              <label><input id="fl-miami" type="checkbox">FL - Miami (9)</label>
            </search-filter>
            <search-filter>
              <search-filter-header>Vehicle title type</search-filter-header>
              <label><input id="clean" type="checkbox">Clean Title (100+)</label>
              <label><input id="salvage" type="checkbox">Salvage Title (100+)</label>
            </search-filter>
            <search-filter>
              <search-filter-header>Fuel type</search-filter-header>
              <label><input id="diesel" type="checkbox">Diesel (22)</label>
            </search-filter>
            <search-filter>
              <search-filter-header>Year</search-filter-header>
              <input id="min-year" aria-label="Minimum year" type="number">
              <input id="max-year" aria-label="Maximum year" type="number">
            </search-filter>
            """
        )
        constraints = VehicleFilterConstraints(
            query="Toyota Camry",
            state="TX",
            min_year=2022,
            featured_items=["Electric Vehicles"],
            title_types=["Clean Title"],
            fuel_types=["Diesel"],
        )

        report = await self.engine._apply_structured_filters(
            self.page,
            constraints,
        )

        self.assertFalse(await self.page.locator("#tx-dallas").is_checked())
        self.assertFalse(await self.page.locator("#fl-miami").is_checked())
        self.assertTrue(await self.page.locator("#clean").is_checked())
        self.assertTrue(await self.page.locator("#diesel").is_checked())
        self.assertEqual(await self.page.locator("#min-year").input_value(), "2022")
        self.assertNotIn("Location", report["facets"])

    async def test_headed_browser_can_be_minimized_with_cdp(self):
        session = AsyncMock()
        session.send.side_effect = [{"windowId": 7}, {}]
        page = SimpleNamespace(
            context=SimpleNamespace(
                new_cdp_session=AsyncMock(return_value=session)
            ),
            bring_to_front=AsyncMock(),
        )

        await self.engine._set_browser_window(page, "minimized")

        session.send.assert_any_await(
            "Browser.setWindowBounds",
            {"windowId": 7, "bounds": {"windowState": "minimized"}},
        )
        session.detach.assert_awaited_once()

    def test_state_is_added_to_free_text_query_once(self):
        constraints = VehicleFilterConstraints(
            query="Lexus",
            state="Maryland",
        )
        self.assertEqual(
            self.engine._build_search_query(constraints),
            "Lexus MD",
        )
        already_present = VehicleFilterConstraints(
            query="Lexus MD",
            state="MD",
        )
        self.assertEqual(
            self.engine._build_search_query(already_present),
            "Lexus MD",
        )

    def test_multiple_locations_are_added_to_query_and_checked_as_or(self):
        constraints = VehicleFilterConstraints(
            query="Toyota Camry",
            locations=["Maryland", "Texas"],
        )
        self.assertEqual(
            self.engine._build_search_query(constraints),
            "Toyota Camry MD TX",
        )
        items = [
            {"title": "2022 TOYOTA CAMRY", "yard_location": "MD - BALTIMORE"},
            {"title": "2023 TOYOTA CAMRY", "yard_location": "TX - DALLAS"},
            {"title": "2024 TOYOTA CAMRY", "yard_location": "FL - MIAMI"},
        ]
        filtered = self.engine._filter_items(items, constraints)
        self.assertEqual(
            [vehicle["yard_location"] for vehicle in filtered],
            ["MD - BALTIMORE", "TX - DALLAS"],
        )


if __name__ == "__main__":
    unittest.main()
