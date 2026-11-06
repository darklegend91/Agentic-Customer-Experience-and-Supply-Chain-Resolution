"""Offline tests for LangGraph routing, evidence use, and approval interrupts."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from backend.app.agents.graph import build_workflow_graph


ORDER_ID = "ORD-ID-Abcd1234"


def classification(intent: str, *, confidence: float = 0.99, provider: str = "laya") -> dict:
    return {
        "schema_version": "1.0",
        "intent": intent,
        "confidence": confidence,
        "classifier_version": "test-laya",
        "classifier_provider": provider,
        "fallback_used": provider != "laya",
        "triage_status": "ready" if provider == "laya" and confidence >= 0.65 else "needs_review",
        "risk_flags": [] if provider == "laya" else ["laya_unavailable_baseline_fallback"],
        "entities": {"order_ids": [ORDER_ID]},
        "review_threshold": 0.65,
        "needs_human_review": True,
        "confidence_calibrated": False,
        "automatic_routing_enabled": False,
    }


def order_evidence() -> dict:
    return {
        "schema_version": "1.0",
        "source_system": "Neon Postgres",
        "as_of": "2026-11-05T00:00:00Z",
        "status": "found",
        "order_id": ORDER_ID,
        "order": {"order_id": ORDER_ID, "status": "shipped"},
        "items": [{"item_id": "ITEM-1", "product_name": "Mixer grinder", "category": "home_appliance", "quantity": "1"}],
        "delivery_events": [
            {"event_id": "EVENT-1", "event_type": "shipped", "event_time": "2026-11-04T10:00:00Z", "location": "Hub", "source": "fixture"}
        ],
        "returns_refunds": [],
        "evidence_refs": {
            "order": [f"order:{ORDER_ID}"],
            "items": ["item:ITEM-1"],
            "delivery_events": ["delivery_event:EVENT-1"],
            "returns_refunds": [],
        },
        "missing_fields": [],
        "eligibility_decided": False,
    }


def initial_state(*, message: str | None = None, order_id: str | None = ORDER_ID) -> dict:
    return {
        "workflow_id": "11111111-1111-4111-8111-111111111111",
        "thread_id": "22222222-2222-4222-8222-222222222222",
        "request_id": "req-test",
        "created_by": "support-agent",
        "ticket_id": None,
        "message": message or f"Please check my order {ORDER_ID}",
        "order_id": order_id,
        "query": "order investigation policy",
        "methods": ["keyword"],
        "top_k": 3,
        "allowed_ticket_ids": ["*"],
        "allowed_order_ids": ["*"],
        "status": "running",
    }


class Day5WorkflowTests(unittest.TestCase):
    def make_graph(self, *, persistence_enabled: bool = False):
        return build_workflow_graph(checkpointer=InMemorySaver(), persistence_enabled=persistence_enabled)

    def test_order_status_routes_to_order_delivery_and_returns_cited_fact(self):
        state = initial_state(message=f"What is the status of order {ORDER_ID}?")
        with (
            patch("backend.app.agents.triage.classify_ticket_message", return_value=classification("order_status")),
            patch("backend.app.agents.investigation.get_order_investigation", return_value=order_evidence()),
        ):
            result = self.make_graph().invoke(state, {"configurable": {"thread_id": state["thread_id"]}})

        self.assertEqual(result["status"], "answer_ready")
        self.assertEqual(result["specialist"], "order_delivery")
        self.assertIn("status 'shipped'", result["answer"])
        self.assertIn(f"order:{ORDER_ID}", result["evidence_refs"])

    def test_unscoped_order_is_rejected_before_classification(self):
        state = initial_state()
        state["allowed_order_ids"] = []
        with patch("backend.app.agents.triage.classify_ticket_message") as classify:
            result = self.make_graph().invoke(state, {"configurable": {"thread_id": state["thread_id"]}})

        classify.assert_not_called()
        self.assertEqual(result["status"], "failed_safe")
        self.assertEqual(result["error_code"], "order_scope_denied")

    def test_classifier_fallback_goes_to_review_without_read_tools(self):
        state = initial_state()
        with (
            patch("backend.app.agents.triage.classify_ticket_message", return_value=classification("order_status", provider="tfidf_fallback")),
            patch("backend.app.agents.investigation.get_order_investigation") as order_lookup,
        ):
            result = self.make_graph().invoke(state, {"configurable": {"thread_id": state["thread_id"]}})

        order_lookup.assert_not_called()
        self.assertEqual(result["specialist"], "manual_review")
        self.assertEqual(result["status"], "escalated")

    def test_consequential_proposal_interrupts_then_approves_simulation_only(self):
        state = initial_state(message=f"My item in order {ORDER_ID} arrived damaged")
        state["workflow_id"] = "33333333-3333-4333-8333-333333333333"
        state["thread_id"] = "44444444-4444-4444-8444-444444444444"
        policy = {
            "status": "found",
            "collection": "test",
            "corpus_scope": "test fixture",
            "missing_fields": [],
            "results": {
                "keyword": [{
                    "document_id": "APPROVED-POLICY",
                    "policy_id": "POLICY-1",
                    "policy_version": "1.0.0",
                    "status": "approved",
                    "marketplace": "IN",
                    "environment_scope": "production",
                    "section_id": "damaged-items",
                    "section_title": "Damage claims",
                    "chunk_id": "chunk-1",
                    "source_uri": "policy://fixture",
                    "source_path": "approved-policy.md",
                    "source_file_sha256": "a" * 64,
                    "excerpt": "Approved policy evidence for the test.",
                }]
            },
        }
        graph = self.make_graph(persistence_enabled=True)
        config = {"configurable": {"thread_id": state["thread_id"]}}
        with (
            patch("backend.app.agents.triage.classify_ticket_message", return_value=classification("damaged_item")),
            patch("backend.app.agents.investigation.get_order_investigation", return_value=order_evidence()),
            patch("backend.app.agents.investigation.retrieve_policy_evidence", return_value=policy),
            patch("backend.app.agents.graph.record_stage_event"),
            patch("backend.app.agents.graph.update_workflow_order_scope"),
            patch("backend.app.agents.graph.save_proposal") as save_proposal,
            patch("backend.app.agents.graph.update_workflow"),
        ):
            paused = graph.invoke(state, config)
            self.assertEqual(paused["status"], "pending_approval")
            self.assertTrue(paused["proposal"]["proposal_id"])
            self.assertIn("__interrupt__", paused)
            persisted_summary = save_proposal.call_args.kwargs["workflow_summary"]
            self.assertEqual(persisted_summary["status"], "pending_approval")
            self.assertEqual(persisted_summary["specialist"], "product_issue")
            self.assertEqual(persisted_summary["proposal_id"], paused["proposal"]["proposal_id"])

            resumed = graph.invoke(
                Command(resume={"decision": "approve", "evidence_valid": True}),
                config,
            )

        self.assertEqual(resumed["status"], "approved_simulation")
        self.assertIn("No external", resumed["answer"])


if __name__ == "__main__":
    unittest.main()
