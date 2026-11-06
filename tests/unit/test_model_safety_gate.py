import unittest
from unittest.mock import Mock, patch
from backend.app.classification import laya


class ModelSafetyGateTests(unittest.TestCase):
    def test_model_checks_safety_before_intent(self):
        router = Mock()
        router.route.return_value.model = "english"
        agent = router.load.return_value
        agent.system_one.side_effect = [
            {"answers": {"input_safety": {"type": "choice", "choice": "safe_support_request", "answer_confidence": .99}}},
            {"answers": {"intent": {"type": "choice", "choice": "order_status", "answer_confidence": .99}}},
        ]
        with patch.object(laya, "_in_process_router", router):
            result = laya.classify_with_laya("Where is my order?")
        self.assertTrue(result["safety_passed"])
        self.assertIn("input_safety", agent.system_one.call_args_list[0].args[1])
        self.assertIn("intent", agent.system_one.call_args_list[1].args[1])

    def test_unsafe_uncertain_or_invalid_verdict_stops_before_intent(self):
        for answer in ({}, {"type": "choice", "choice": "unsafe_or_uncertain", "answer_confidence": .99}, {"type": "choice", "choice": "safe_support_request", "answer_confidence": .5}):
            with self.subTest(answer=answer):
                router = Mock()
                router.route.return_value.model = "english"
                agent = router.load.return_value
                agent.system_one.return_value = {"answers": {"input_safety": answer}}
                with patch.object(laya, "_in_process_router", router):
                    result = laya.classify_with_laya("Where is my order?")
                self.assertFalse(result["safety_passed"])
                self.assertTrue(result["force_review"])
                agent.system_one.assert_called_once()
