import unittest
from unittest.mock import MagicMock, patch

from backend.app.approval import workflow_state


class WorkflowConnectionPoolTests(unittest.TestCase):
    def test_audit_pipeline_surfaces_database_errors(self):
        pool = MagicMock()
        connection = pool.connection.return_value.__enter__.return_value
        connection.pipeline.return_value.__exit__.side_effect = RuntimeError("flush failed")
        with patch.object(workflow_state, "_get_pool", return_value=pool):
            with self.assertRaises(workflow_state.WorkflowStoreUnavailable):
                workflow_state.record_stage_event('00000000-0000-0000-0000-000000000001', stage='input', event_type='input_validated')
        connection.transaction.assert_called_once()

    def test_transactions_reuse_pool_and_return_connections_on_failure(self):
        pool = MagicMock()
        connection = pool.connection.return_value.__enter__.return_value
        with (
            patch.object(workflow_state, "_dsn", return_value="postgresql://fixture"),
            patch("backend.app.approval.workflow_state.ConnectionPool", create=True, return_value=pool) as factory,
        ):
            factory.__getitem__.return_value = factory
            try:
                for _ in range(2):
                    with workflow_state._connection() as current:
                        self.assertIs(current, connection)
                with self.assertRaises(workflow_state.WorkflowStoreUnavailable):
                    with workflow_state._connection():
                        raise RuntimeError("transaction failed")
                factory.assert_called_once()
                self.assertEqual(pool.connection.call_count, 3)
                self.assertEqual(pool.connection.return_value.__exit__.call_count, 3)
            finally:
                if hasattr(workflow_state, "close_workflow_pool"):
                    workflow_state.close_workflow_pool()
