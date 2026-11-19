import unittest
from unittest.mock import Mock, patch
from backend.app.classification import laya


class ModelSafetyGateTests(unittest.TestCase):
    def setUp(self):
        cache = patch.dict(laya._CLASSIFY_CACHE, {}, clear=True)
        cache.start()
        self.addCleanup(cache.stop)

    def test_model_checks_safety_before_intent(self):
        router = Mock()
        router.route.return_value.model = "english"
        agent = router.load.return_value
        agent.system_one.side_effect = lambda state, questions: (
            {"answers": {"input_safety": {"type": "choice", "choice": "safe_support_request", "answer_confidence": .99}}}
            if "input_safety" in questions else
            {"answers": {"intent": {"type": "choice", "choice": "order_status", "answer_confidence": .99}}}
        )
        message = "Please investigate the safety stage fixture"
        with patch.object(laya, "_in_process_router", router):
            result = laya.classify_with_laya(message)
        self.assertTrue(result["safety_passed"])
        calls = [call for call in agent.system_one.call_args_list if call.args[0].get("ticket_message") == message]
        self.assertEqual(len(calls), 2)
        self.assertIn("input_safety", calls[0].args[1])
        self.assertIn("intent", calls[1].args[1])

    def test_unsafe_uncertain_or_invalid_verdict_stops_before_intent(self):
        for index, answer in enumerate(({}, {"type": "choice", "choice": "unsafe_or_uncertain", "answer_confidence": .99}, {"type": "choice", "choice": "safe_support_request", "answer_confidence": .5})):
            with self.subTest(answer=answer):
                router = Mock()
                router.route.return_value.model = "english"
                agent = router.load.return_value
                agent.system_one.return_value = {"answers": {"input_safety": answer}}
                message = f"Please investigate safety rejection fixture {index}"
                with patch.object(laya, "_in_process_router", router):
                    result = laya.classify_with_laya(message)
                self.assertFalse(result["safety_passed"])
                self.assertTrue(result["force_review"])
                # API lifespan warmup threads use the same process-wide router;
                # count only this test's input, never an unrelated warmup call.
                calls = [call for call in agent.system_one.call_args_list if call.args[0].get("ticket_message") == message]
                self.assertEqual(len(calls), 1)
