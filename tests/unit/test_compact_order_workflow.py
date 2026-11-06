import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from langgraph.checkpoint.memory import InMemorySaver
from backend.app.agents.graph import build_workflow_graph
from tests.agents.test_day5_workflow import initial_state, order_evidence
from tests.unit import test_workflow_optimizations as fixtures

class CompactOrderWorkflowTests(unittest.TestCase):
    def test_consequential_route_still_interrupts_for_approval(self):
        # Exercise orchestration with a separately tested rules decision; the
        # status optimization must not consume a consequential proposal.
        resolution={'outcome':'proposal','requires_approval':True,'proposal':{
            'action_kind':'item_remedy_review_simulation','summary':'Review damage evidence',
            'permitted_options':['approve_simulation','reject'],'evidence_refs':[],'policy_versions':[]}}
        with patch('backend.app.agents.graph.triage_ticket',return_value={'classification':{'intent':'damaged_item'},'triage_ready':True}), patch('backend.app.agents.graph.product_issue_specialist',return_value={'evidence':{},'evidence_refs':[],'status':'running'}), patch('backend.app.agents.graph.evaluate_resolution',return_value=resolution):
            graph=build_workflow_graph(checkpointer=InMemorySaver(),persistence_enabled=False)
            result=graph.invoke(initial_state(message='My item arrived damaged'), {'configurable':{'thread_id':'approval-regression'}})
        self.assertEqual(result['status'],'pending_approval')
        self.assertTrue(result['__interrupt__'])
        self.assertEqual(result['proposal']['action_execution_status'],'not_available')

    @patch.dict(os.environ, {'APP_ENV':'local','LLM_ENABLED':'false'})
    def test_audit_batches_preserve_every_check_before_completion(self):
        evidence=order_evidence(); evidence['as_of']=datetime.now(timezone.utc).isoformat()
        with patch('backend.app.tools.ticket_tools.classify_with_laya',return_value=fixtures.WorkflowOptimizationTests().safe_model_result()), patch('backend.app.agents.investigation.get_order_investigation',return_value=evidence), patch('backend.app.agents.graph.update_workflow_order_scope'), patch('backend.app.agents.graph.record_stage_events') as batches, patch('backend.app.agents.graph.update_workflow') as finish:
            result=build_workflow_graph(persistence_enabled=True).invoke(initial_state(message='Where is my order?'))
        self.assertEqual(result['status'],'answer_ready')
        self.assertEqual(batches.call_count,2)
        entries=[entry for call in batches.call_args_list for entry in call.args[1]]
        self.assertEqual([e['stage'] for e in entries],['input','triage','supervisor','order_delivery','order_delivery','evidence','policy_rules','response','output_validation'])
        self.assertEqual([e['occurred_at'] for e in entries], sorted(e['occurred_at'] for e in entries))
        finish.assert_called_once()
        trace=finish.call_args.kwargs['summary']['completed_trace']
        self.assertEqual(trace['answer'],result['answer'])
        self.assertNotIn('message',trace)

    @patch.dict(os.environ, {'APP_ENV':'local','LLM_ENABLED':'false'})
    def test_readonly_request_keeps_checks_with_three_checkpoint_steps(self):
        evidence=order_evidence(); evidence['as_of']=datetime.now(timezone.utc).isoformat()
        with patch('backend.app.tools.ticket_tools.classify_with_laya',return_value=fixtures.WorkflowOptimizationTests().safe_model_result()) as model, patch('backend.app.agents.investigation.get_order_investigation',return_value=evidence) as lookup, patch('backend.app.agents.investigation.retrieve_policy_evidence') as policy:
            steps=list(build_workflow_graph(persistence_enabled=False).stream(initial_state(message='Where is my order?'),stream_mode='updates'))
        self.assertEqual(len(steps),3, [list(step) for step in steps])
        model.assert_called_once(); lookup.assert_called_once(); policy.assert_not_called()
        self.assertIn('read_only_order', steps[1])
        self.assertEqual(steps[1]['read_only_order']['status'],'answer_ready')
        self.assertTrue(steps[1]['read_only_order']['evidence_refs'])

    @patch.dict(os.environ, {'APP_ENV':'local','LLM_ENABLED':'false'})
    def test_unsafe_message_cannot_enter_compact_order_path(self):
        unsafe={**fixtures.WorkflowOptimizationTests().safe_model_result(),'safety_passed':False}
        with patch('backend.app.tools.ticket_tools.classify_with_laya',return_value=unsafe), patch('backend.app.agents.investigation.get_order_investigation') as lookup:
            steps=list(build_workflow_graph(persistence_enabled=False).stream(initial_state(message='Where is my order?'),stream_mode='updates'))
        lookup.assert_not_called()
        self.assertFalse(any('read_only_order' in step for step in steps))
