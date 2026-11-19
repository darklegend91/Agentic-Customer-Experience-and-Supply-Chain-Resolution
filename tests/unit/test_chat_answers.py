"""Customer-visible answers must distinguish useful results from refusals."""

import os
import unittest
from unittest.mock import patch

from backend.app.tools.investigation_tools import investigate_ticket
from backend.app.tools.ticket_tools import classify_ticket_message
from tests.agents.test_day5_workflow import classification as workflow_classification, order_evidence


def classification(intent):
    return {**workflow_classification(intent), "confidence_calibrated": False, "entities": {"order_ids": []}}


EMPTY_POLICY = {"status": "insufficient_data", "results": {}, "collection": None,
                "corpus_scope": "synthetic development-only", "missing_fields": ["relevant_policy_passage"]}


@patch.dict(os.environ, {"APP_ENV": "local", "LLM_ENABLED": "false"})
class ChatAnswerTests(unittest.TestCase):
    def test_unrecognized_package_uses_a_single_clarification_path_without_models(self):
        with patch("backend.app.tools.ticket_tools.classify_with_laya") as model, patch(
            "backend.app.tools.ticket_tools.run_intent_classifier"
        ) as baseline:
            for message in (
                "what to do if i recieved a package that i have not ordered?",
                "i have recieve somthing that i have not ordered?",
                "I received an unrecognized parcel.",
            ):
                result = classify_ticket_message(message)
                self.assertEqual(result["intent"], "unrecognized_package", message)
                self.assertEqual(result["triage_status"], "needs_review", message)
                self.assertTrue(result["needs_human_review"], message)
                self.assertIn("unrecognized_package_needs_confirmation", result["risk_flags"], message)
        model.assert_not_called()
        baseline.assert_not_called()

    def test_unrecognized_package_asks_which_situation_applies_before_evidence_lookups(self):
        with patch(
            "backend.app.tools.investigation_tools.classify_ticket_message",
            return_value=classification("unrecognized_package"),
        ), patch("backend.app.tools.investigation_tools.search_policy", return_value=EMPTY_POLICY) as policy, patch(
            "backend.app.tools.investigation_tools.get_order_investigation"
        ) as orders:
            result = investigate_ticket(
                message="I received a package that I did not order.",
                order_id="ORD-ID-Abcd1234",
            )
        self.assertEqual(result["status"], "needs_information")
        self.assertEqual(result["reason_codes"], ["unrecognized_package_needs_confirmation"])
        self.assertIn("different item", result["answer"])
        self.assertIn("not connected", result["answer"])
        self.assertIn("shipping label", result["answer"])
        policy.assert_not_called()
        orders.assert_not_called()

    def test_password_reset_is_unsupported_without_calling_models(self):
        with patch("backend.app.tools.ticket_tools.classify_with_laya", return_value={
            "candidate_intent": "exchange_request", "top_class_probability": .99, "model_version": "test", "safety_passed": True,
        }) as model, patch("backend.app.tools.ticket_tools.run_intent_classifier", return_value={
            "candidate_intent": "exchange_request", "top_class_probability": .99,
        }):
            for message in ("reset my password", "reset password", "Please reset the password", "I forgot password", "Password reset please"):
                result = classify_ticket_message(message)
                self.assertEqual(result["intent"], "other_or_unsupported", message)
        self.assertEqual(result["intent"], "other_or_unsupported")
        self.assertFalse(result["automatic_routing_enabled"])
        self.assertIn("unsupported_account_request", result["risk_flags"])
        model.assert_not_called()

    def test_unsupported_request_explains_scope_without_evidence_lookups(self):
        with patch("backend.app.tools.investigation_tools.classify_ticket_message", return_value=classification("other_or_unsupported")), patch(
            "backend.app.tools.investigation_tools.search_policy", return_value=EMPTY_POLICY
        ) as policy, patch("backend.app.tools.investigation_tools.get_order_investigation") as orders:
            result = investigate_ticket(message="When was the Python language launched?")
        self.assertEqual(result["status"], "escalated")
        self.assertIn("can't answer", result["answer"].lower())
        self.assertIn("orders", result["answer"].lower())
        policy.assert_not_called()
        orders.assert_not_called()

    def test_password_reply_never_claims_to_reset_account(self):
        with patch("backend.app.tools.investigation_tools.search_policy", return_value=EMPTY_POLICY):
            result = investigate_ticket(message="Please reset my password.")
        self.assertEqual(result["status"], "escalated")
        self.assertIn("can't reset", result["answer"].lower())
        self.assertIn("sign-in", result["answer"].lower())
        self.assertNotIn("completed successfully", result["answer"])

    def test_missing_order_requests_details_instead_of_claiming_success(self):
        with patch("backend.app.tools.investigation_tools.classify_ticket_message", return_value=classification("order_status")), patch(
            "backend.app.tools.investigation_tools.search_policy", return_value=EMPTY_POLICY
        ):
            result = investigate_ticket(message="Where is my order?")
        self.assertEqual(result["status"], "needs_information")
        self.assertIn("order ID", result["answer"])

    def test_stale_records_do_not_ask_for_an_order_id_already_provided(self):
        evidence = order_evidence()
        evidence["as_of"] = "2020-01-01T00:00:00Z"
        with patch("backend.app.tools.investigation_tools.classify_ticket_message", return_value=classification("order_status")), patch(
            "backend.app.tools.investigation_tools.search_policy", return_value=EMPTY_POLICY
        ), patch("backend.app.tools.investigation_tools.get_order_investigation", return_value=evidence), patch(
            "backend.app.tools.investigation_tools.get_customer_support_context", return_value=None
        ):
            result = investigate_ticket(message="Where is my order?", order_id="ORD-ID-Abcd1234")
        self.assertEqual(result["status"], "escalated")
        self.assertIn("current", result["answer"])
        self.assertNotIn("Please share the order ID", result["answer"])

    def test_verified_status_still_returns_a_grounded_customer_answer(self):
        with patch("backend.app.tools.investigation_tools.classify_ticket_message", return_value=classification("order_status")), patch(
            "backend.app.tools.investigation_tools.search_policy", return_value=EMPTY_POLICY
        ), patch("backend.app.tools.investigation_tools.get_order_investigation", return_value=order_evidence()), patch(
            "backend.app.tools.investigation_tools.get_customer_support_context", return_value=None
        ):
            result = investigate_ticket(message="Where is my order ORD-ID-Abcd1234?", order_id="ORD-ID-Abcd1234")
        self.assertEqual(result["status"], "answer_ready")
        self.assertIn("is marked as shipped", result["answer"])
        self.assertTrue(result["evidence_refs"])

    def test_invalid_source_provenance_cannot_be_presented_as_answered(self):
        evidence = order_evidence()
        evidence["evidence_refs"]["items"] = [""]
        with patch("backend.app.tools.investigation_tools.classify_ticket_message", return_value=classification("order_status")), patch(
            "backend.app.tools.investigation_tools.search_policy", return_value=EMPTY_POLICY
        ), patch("backend.app.tools.investigation_tools.get_order_investigation", return_value=evidence), patch(
            "backend.app.tools.investigation_tools.get_customer_support_context", return_value=None
        ):
            result = investigate_ticket(message="Where is my order?", order_id="ORD-ID-Abcd1234")
        self.assertNotEqual(result["status"], "answer_ready")
        self.assertIn("evidence_validation_failed", result["reason_codes"])
