import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app.main import app
from tests.api.test_day5_workflow_api import WORKFLOW


class SnapshotTests(unittest.TestCase):
    @patch.dict(os.environ, {"APP_ENV": "local", "OIDC_ISSUER": "", "OIDC_AUDIENCE": "", "WORKFLOW_API_TOKEN": "test-support-token", "WORKFLOW_REVIEWER_TOKEN": "test-reviewer-token", "WORKFLOW_API_ACTOR_ID": "support-agent-1"})
    def test_running_snapshot_does_not_load_full_checkpoint(self):
        row = {"created_by": "support-agent-1", "order_id": None, "ticket_id": None, "status": "running"}
        with TestClient(app) as client, patch("backend.app.api.routes.workflows.get_workflow", return_value=row), patch("backend.app.api.routes.workflows.get_workflow_response", return_value={**WORKFLOW, "status": "running"}), patch("backend.app.api.routes.workflows.get_workflow_events", return_value=[]), patch("backend.app.api.routes.workflows.get_workflow_trace") as trace:
            response = client.get(f"/workflows/{WORKFLOW['workflow_id']}/snapshot", headers={"Authorization": "Bearer test-support-token"})
        trace.assert_not_called()
        self.assertEqual(response.status_code, 200)

    @patch.dict(os.environ, {"APP_ENV": "local", "OIDC_ISSUER": "", "OIDC_AUDIENCE": "", "WORKFLOW_API_TOKEN": "test-support-token", "WORKFLOW_REVIEWER_TOKEN": "test-reviewer-token", "WORKFLOW_API_ACTOR_ID": "support-agent-1"})
    def test_snapshot_authorizes_before_fetching_checkpoint(self):
        row = {"created_by": "another-agent", "order_id": None, "ticket_id": None}
        with TestClient(app) as client, patch("backend.app.api.routes.workflows.get_workflow", return_value=row), patch("backend.app.api.routes.workflows.get_workflow_trace") as trace:
            response = client.get(f"/workflows/{WORKFLOW['workflow_id']}/snapshot", headers={"Authorization": "Bearer test-support-token"})
        self.assertEqual(response.status_code, 403)
        trace.assert_not_called()

    @patch.dict(os.environ, {"APP_ENV": "local", "OIDC_ISSUER": "", "OIDC_AUDIENCE": "", "WORKFLOW_API_TOKEN": "test-support-token", "WORKFLOW_REVIEWER_TOKEN": "test-reviewer-token", "WORKFLOW_API_ACTOR_ID": "support-agent-1"})
    def test_snapshot_reads_workflow_row_once(self):
        row = {"created_by": "support-agent-1", "order_id": None, "ticket_id": None}
        with TestClient(app) as client, patch("backend.app.api.routes.workflows.get_workflow", return_value=row) as read, patch("backend.app.api.routes.workflows.get_workflow_response", return_value=WORKFLOW), patch("backend.app.api.routes.workflows.get_workflow_events", return_value=[]), patch("backend.app.api.routes.workflows.get_workflow_trace", return_value={"workflow_id": WORKFLOW["workflow_id"], "status": "answer_ready"}):
            response = client.get(f"/workflows/{WORKFLOW['workflow_id']}/snapshot", headers={"Authorization": "Bearer test-support-token"})
        self.assertEqual(response.status_code, 200)
        read.assert_called_once()
        self.assertEqual(response.json()["workflow"]["status"], "answer_ready")
