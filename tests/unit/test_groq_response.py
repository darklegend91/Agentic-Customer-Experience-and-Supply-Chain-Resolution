import json
import os
import unittest
from unittest.mock import Mock, patch
import httpx
from backend.app.agents import response_generation as response
from tests.agents.test_day5_workflow import initial_state, order_evidence

ENV={'LLM_ENABLED':'true','LLM_PROVIDER':'groq','GROQ_API_KEY':'test-key','GROQ_MODEL':'openai/gpt-oss-20b','LLM_MODEL':'obsolete-other-provider'}

def state():
    result=initial_state(message='Where is my order? contact me at private@example.com')
    evidence=order_evidence(); evidence['order']['status']='delivered'
    result.update(classification={'intent':'order_status'},evidence={'order':evidence},evidence_refs=evidence['evidence_refs']['order'])
    return result

class GroqResponseTests(unittest.TestCase):
    def completion(self, composition):
        r=Mock(); r.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(composition)}}]}; return r

    @patch.dict(os.environ, ENV)
    def test_groq_composes_grounded_answer_and_does_not_send_raw_ticket(self):
        s=state(); fact=response.recorded_claims(s)[0]['text']
        plan={'opening':"I've checked the details for you.",'facts':{'fact_0':fact},'closing':'If it hasn’t arrived, please let us know.'}
        with patch('httpx.Client.post',return_value=self.completion(plan)) as post:
            result=response.draft_grounded_response(s)
        self.assertEqual(result['draft_provider'],'groq')
        self.assertTrue(result['draft']['answer'].startswith("I've checked"))
        self.assertEqual(result['draft']['claims'],response.recorded_claims(s))
        payload=post.call_args.kwargs['json']
        self.assertEqual(payload['model'],'openai/gpt-oss-20b')
        self.assertEqual(payload['response_format']['type'],'json_schema')
        self.assertNotIn('private@example.com',str(payload))
        self.assertNotIn('tools',payload)
        self.assertEqual(post.call_args.args[0],'https://api.groq.com/openai/v1/chat/completions')

    @patch.dict(os.environ, ENV)
    def test_invented_refund_or_missing_fact_falls_back(self):
        for plan in ({'opening':'','facts':{'fact_0':'Your refund is approved.'},'closing':''}, {'opening':'','facts':{},'closing':''}):
            with self.subTest(plan=plan),patch('httpx.Client.post',return_value=self.completion(plan)):
                result=response.draft_grounded_response(state())
            self.assertEqual(result['draft_provider'],'deterministic_fallback')
            self.assertNotIn('approved',result['draft']['answer'])

    @patch.dict(os.environ, ENV)
    def test_timeout_returns_verified_template(self):
        with patch('httpx.Client.post',side_effect=httpx.ReadTimeout('timeout')):
            result=response.draft_grounded_response(state())
        self.assertEqual(result['draft_provider'],'deterministic_fallback')
        self.assertIsNone(result['draft_error_code'])
        self.assertIn('marked as delivered',result['draft']['answer'])

    @patch.dict(os.environ, {**ENV,'GROQ_API_KEY':''})
    def test_empty_placeholder_does_not_make_network_call(self):
        with patch('httpx.Client.post') as post:
            result=response.draft_grounded_response(state())
        post.assert_not_called()
        self.assertEqual(result['draft_provider'],'deterministic_fallback')
