"""Exercise MCP discovery and one real review-only tool call in process."""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from mcp import Client  # noqa: E402
from backend.app.mcp_server.server import mcp  # noqa: E402


class Day4McpTests(unittest.TestCase):
    def test_tools_are_discoverable_and_classifier_returns_structured_result(self):
        async def exercise():
            async with Client(mcp) as client:
                listing = await client.list_tools(cache_mode="bypass")
                by_name = {tool.name: tool for tool in listing.tools}
                self.assertEqual(set(by_name), {
                    "get_ticket_details",
                    "classify_ticket",
                    "get_order_summary",
                    "get_order_investigation",
                    "list_delivery_events",
                    "get_return_refund_status",
                    "search_policy",
                    "investigate_ticket",
                })
                self.assertTrue(by_name["get_order_summary"].annotations.read_only_hint)
                self.assertFalse(by_name["search_policy"].annotations.open_world_hint)
                self.assertIn("maximum", by_name["list_delivery_events"].input_schema["properties"]["limit"])

                with patch("backend.app.mcp_server.server.run_ticket_classification", return_value={
                    "intent": "damaged_item",
                    "confidence": 0.4,
                    "classifier_version": "test-model",
                    "triage_status": "ready",
                    "risk_flags": [],
                    "needs_human_review": True,
                    "confidence_calibrated": False,
                    "automatic_routing_enabled": False,
                    "review_threshold": 0.65,
                }):
                    result = await client.call_tool("classify_ticket", {
                        "message": "My package arrived damaged and I need help.",
                    })
                self.assertFalse(result.is_error)
                self.assertTrue(result.structured_content["needs_human_review"])
                self.assertFalse(result.structured_content["confidence_calibrated"])

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
