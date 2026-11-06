import os
import unittest
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
from backend.app.observability import tracing
from backend.app.approval.service import _graph_config

class LangfuseMonitoringTests(unittest.TestCase):
    def test_export_mask_removes_raw_content_and_error_details(self):
        attributes={'langfuse.observation.input':json.dumps({'message':'private text','status':'running'}), 'langfuse.observation.metadata.database_url':'secret-dsn', 'langfuse.observation.status_message':'secret-dsn'}
        params=SimpleNamespace(spans={'span':SimpleNamespace(attributes=attributes)})
        patch=tracing.mask_trace_spans(params=params).span_patches['span']
        self.assertNotIn('private text',str(patch.set_attributes))
        self.assertNotIn('secret-dsn',str(patch.set_attributes))
        self.assertIn('langfuse.observation.metadata.database_url',patch.delete_attributes)

    @patch.dict(os.environ, {'LANGFUSE_PUBLIC_KEY':'test-public','LANGFUSE_SECRET_KEY':'test-secret'})
    def test_callback_uses_supported_sdk_arguments(self):
        with patch.object(tracing,'get_langfuse_client',return_value=Mock()), patch('langfuse.langchain.CallbackHandler') as handler:
            tracing.get_langfuse_callback(session_id='workflow-1',user_id='actor',metadata={'workflow_id':'workflow-1'})
        handler.assert_called_once_with(public_key='test-public')

    def test_trace_metadata_links_workflow_without_raw_actor(self):
        with patch('backend.app.approval.service.get_langfuse_callback',return_value=Mock()):
            config=_graph_config('thread',workflow_id='workflow-1',user_id='person@example.com',tags=['workflow-execution'])
        self.assertEqual(config['metadata']['langfuse_session_id'],'workflow-1')
        self.assertNotIn('person@example.com',str(config['metadata']))

    def test_payload_mask_keeps_diagnostics_and_drops_content(self):
        result=tracing.mask_trace_data(data={'message':'secret customer text', 'evidence':{'token':'sk-secret'}, 'classification':{'intent':'order_status','confidence':.9},'status':'answer_ready'})
        self.assertNotIn('secret',str(result))
        self.assertEqual(result['classification']['intent'],'order_status')
        self.assertEqual(result['status'],'answer_ready')

    def test_monitoring_outage_does_not_block_work(self):
        with patch.object(tracing,'get_langfuse_client',return_value=None):
            with tracing.trace_stage('test'):
                pass

    def test_monitoring_does_not_swallow_business_failure(self):
        client=Mock(); context=Mock(); context.__enter__=Mock(return_value=Mock()); context.__exit__=Mock()
        client.start_as_current_observation.return_value=context
        with patch.object(tracing,'get_langfuse_client',return_value=client):
            with self.assertRaises(ValueError):
                with tracing.trace_stage('test'):
                    raise ValueError('sensitive input')
        context.__exit__.assert_called_once_with(None,None,None)
