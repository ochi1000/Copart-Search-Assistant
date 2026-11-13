import asyncio
import json
import unittest

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.operations import OperationManager
from backend.agent.service import AgentService
from backend.core.errors import InvalidSearchRequest
from backend.core.errors import LLMUnavailable


class FakeCopartService:
    pass


class FakeAgentService:
    async def handle_message(self, message, session_id, publish):
        await publish("thinking", {})
        await publish("search_started", {"query": message})
        await publish(
            "verification_required",
            {
                "message": "Complete verification",
                "live_url": "https://browser.example/live/session",
                "expires_in_seconds": 90,
            },
        )
        await publish("verification_completed", {})
        search = {
            "search_id": "search-1",
            "vehicles": [{
                "lot_number": "12345678",
                "title": "2024 TOYOTA CAMRY",
                "image_url": "https://example.test/camry.jpg",
            }],
        }
        await publish("search_results", search)
        return {"message": "I found one Camry.", "search": search}


class FailingAgentService:
    async def handle_message(self, message, session_id, publish):
        raise InvalidSearchRequest("Please provide a vehicle make or model.")


class UnavailableAgentService:
    async def handle_message(self, message, session_id, publish):
        raise LLMUnavailable()


class APITests(unittest.TestCase):
    def _client(self, agent=None):
        app = create_app(
            copart_service=FakeCopartService(),
            agent_service=agent or FakeAgentService(),
            operation_manager=OperationManager(),
        )
        return TestClient(app)

    def test_message_operation_streams_replayable_events(self):
        with self._client() as client:
            response = client.post(
                "/api/v1/messages",
                json={"message": "Find a Toyota Camry", "session_id": "demo"},
            )
            self.assertEqual(response.status_code, 202)
            operation_id = response.json()["operation_id"]

            stream = client.get(f"/api/v1/operations/{operation_id}/events")
            self.assertEqual(stream.status_code, 200)
            events = [
                json.loads(line.removeprefix("data: "))
                for line in stream.text.splitlines()
                if line.startswith("data: ")
            ]
            event_types = [event["type"] for event in events]
            self.assertLessEqual(
                set(event_types),
                {
                    "thinking",
                    "search_started",
                    "verification_required",
                    "verification_completed",
                    "completed",
                    "failed",
                    "cancelled",
                },
            )
            self.assertEqual(event_types[0], "thinking")
            self.assertIn("search_started", event_types)
            self.assertNotIn("accepted", event_types)
            self.assertNotIn("search_results", event_types)
            self.assertNotIn("assistant_message", event_types)
            self.assertIn("verification_required", event_types)
            verification = next(
                event for event in events
                if event["type"] == "verification_required"
            )
            self.assertEqual(
                verification["data"]["live_url"],
                "https://browser.example/live/session",
            )
            self.assertIn("verification_completed", event_types)
            self.assertEqual(event_types[-1], "completed")
            completed = events[-1]
            self.assertTrue(
                completed["data"]["result"]["search"]["vehicles"][0]["image_url"]
            )

            resumed = client.get(
                f"/api/v1/operations/{operation_id}/events",
                headers={"Last-Event-ID": events[-2]["event_id"]},
            )
            resumed_events = [
                json.loads(line.removeprefix("data: "))
                for line in resumed.text.splitlines()
                if line.startswith("data: ")
            ]
            self.assertEqual(
                [event["type"] for event in resumed_events],
                ["completed"],
            )

            status = client.get(f"/api/v1/operations/{operation_id}")
            self.assertEqual(status.json()["status"], "completed")

    def test_omitted_session_id_starts_a_new_chat(self):
        with self._client() as client:
            first = client.post("/api/v1/messages", json={"message": "first"})
            second = client.post("/api/v1/messages", json={"message": "second"})
            self.assertNotEqual(
                first.json()["session_id"],
                second.json()["session_id"],
            )

    def test_failure_is_streamed_as_safe_public_error(self):
        with self._client(FailingAgentService()) as client:
            response = client.post(
                "/api/v1/messages",
                json={"message": "search"},
            )
            operation_id = response.json()["operation_id"]
            stream = client.get(f"/api/v1/operations/{operation_id}/events")
            self.assertIn("event: failed", stream.text)
            self.assertIn("INVALID_REQUEST", stream.text)
            self.assertNotIn("Traceback", stream.text)

    def test_llm_connection_failure_has_a_specific_public_error(self):
        with self._client(UnavailableAgentService()) as client:
            response = client.post(
                "/api/v1/messages",
                json={"message": "Find hybrid vehicles"},
            )
            operation_id = response.json()["operation_id"]
            stream = client.get(f"/api/v1/operations/{operation_id}/events")
            self.assertIn("LLM_UNAVAILABLE", stream.text)
            self.assertIn("language service", stream.text)

    def test_unknown_operation_returns_friendly_404(self):
        with self._client() as client:
            response = client.get("/api/v1/operations/missing")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["code"], "OPERATION_NOT_FOUND")

    def test_invalid_message_body_uses_stable_error_contract(self):
        with self._client() as client:
            response = client.post(
                "/api/v1/messages",
                json={"message": ""},
            )
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["code"], "INVALID_REQUEST")


class OperationManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancellation_emits_terminal_event(self):
        manager = OperationManager()
        started = asyncio.Event()

        async def runner(publish):
            started.set()
            await asyncio.Event().wait()

        operation = await manager.start("demo", runner)
        await started.wait()
        await manager.cancel(operation.operation_id)
        await operation.task

        event_types = [event.type for event in operation.events]
        self.assertEqual(event_types[0], "accepted")
        self.assertEqual(event_types[-1], "cancelled")
        self.assertEqual(operation.status, "cancelled")

    async def test_immediate_cancellation_is_not_lost(self):
        manager = OperationManager()

        async def runner(publish):
            await asyncio.Event().wait()

        operation = await manager.start("demo", runner)
        await manager.cancel(operation.operation_id)
        self.assertEqual(operation.status, "cancelled")
        self.assertEqual(operation.events[-1].type, "cancelled")


class AgentGroundingTests(unittest.TestCase):
    def test_exact_search_keeps_response_without_duplicate_listing_text(self):
        reply = AgentService._grounded_reply(
            (
                "I found four options that fit your search.\n"
                "- **2024 Tesla Model Y** — Clean title, 50,358 mi.\n"
                "- **2023 Tesla Model 3** — Salvage title, 20,100 mi."
            ),
            {
                "count_returned": 2,
                "match_status": "exact",
                "filter_warnings": [],
                "vehicles": [
                    {"title": "2024 Tesla Model Y", "lot_number": "12345678"},
                    {"title": "2023 Tesla Model 3", "lot_number": "87654321"},
                ],
            },
        )
        self.assertEqual(reply, "I found four options that fit your search.")

    def test_listing_only_response_gets_short_conversational_intro(self):
        reply = AgentService._grounded_reply(
            "- **2024 Tesla Model Y** — Clean title, 50,358 mi.",
            {
                "count_returned": 1,
                "match_status": "exact",
                "filter_warnings": [],
                "vehicles": [{"title": "2024 Tesla Model Y"}],
            },
        )
        self.assertEqual(reply, "Here are the matches I found.")

    def test_partial_match_reply_does_not_claim_unavailable_filter_matched(self):
        reply = AgentService._grounded_reply(
            "Here are hybrid vehicles with Buy It Now.",
            {
                "count_returned": 4,
                "match_status": "partial_matches",
                "filter_warnings": [
                    "No available 'Fuel type' option matched: Hybrid"
                ],
            },
        )
        self.assertIn("couldn't confirm the Hybrid filter", reply)
        self.assertIn("4 similar options", reply)
        self.assertNotIn("Here are hybrid vehicles", reply)


if __name__ == "__main__":
    unittest.main()
