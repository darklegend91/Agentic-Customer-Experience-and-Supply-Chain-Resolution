"""Authentication and schema boundary tests for the Day 5 workflow API."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import app


WORKFLOW = {
    "schema_version": "1.0",
    "workflow_id": "11111111-1111-4111-8111-111111111111",
    "thread_id": "22222222-2222-4222-8222-222222222222",
    "status": "answer_ready",
    "classification": None,
    "specialist": "order_delivery",
    "answer": "The order record is available.",
    "disposition": "answer",
    "evidence_refs": ["order:ORD-ID-test1234"],
    "missing_information": [],
    "reason_codes": [],
    "proposal": None,
    "error_code": None,
}


class Day5WorkflowApiTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "APP_ENV": "local",
            "OIDC_ISSUER": "",
            "OIDC_AUDIENCE": "",
            "WORKFLOW_API_TOKEN": "test-support-token",
            "WORKFLOW_REVIEWER_TOKEN": "test-reviewer-token",
            "WORKFLOW_API_ACTOR_ID": "support-agent-1",
            "WORKFLOW_REVIEWER_ID": "reviewer-1",
        })
        self.environment.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.environment.stop()

    def test_workflow_route_requires_bearer_authentication(self):
        response = self.client.post("/workflows", json={
            "schema_version": "1.0",
            "message": "Where is my order?",
        })
        self.assertEqual(response.status_code, 401)

    def test_support_token_starts_workflow_and_reviewer_token_cannot(self):
        body = {"schema_version": "1.0", "message": "Where is my order?"}
        queued_response = {**WORKFLOW, "status": "running"}
        with (
            patch(
                "backend.app.api.routes.workflows.queue_workflow",
                return_value=(queued_response, {"workflow_id": WORKFLOW["workflow_id"]}),
            ) as queue,
            patch("backend.app.api.routes.workflows.execute_workflow") as execute,
        ):
            response = self.client.post(
                "/workflows",
                headers={"Authorization": "Bearer test-support-token"},
                json=body,
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "running")
        self.assertEqual(queue.call_args.kwargs["message"], "Where is my order?")
        execute.assert_called_once()

        response = self.client.post(
            "/workflows",
            headers={"Authorization": "Bearer test-reviewer-token"},
            json=body,
        )
        self.assertEqual(response.status_code, 403)

    def test_approval_route_uses_reviewer_identity_and_versioned_body(self):
        workflow_id = WORKFLOW["workflow_id"]
        proposal_id = "33333333-3333-4333-8333-333333333333"
        response_payload = {
            "schema_version": "1.0",
            "proposal_id": proposal_id,
            "workflow_id": workflow_id,
            "decision": "approve",
            "status": "approved_simulation",
            "workflow": WORKFLOW,
        }
        proposal = {"created_by": "support-agent-1", "ticket_id": None, "order_id": None}
        with (
            patch("backend.app.api.routes.approvals.get_proposal", return_value=proposal),
            patch("backend.app.api.routes.approvals.decide_proposal", return_value=response_payload) as decide,
        ):
            response = self.client.post(
                f"/approvals/proposals/{proposal_id}/decision",
                headers={
                    "Authorization": "Bearer test-reviewer-token",
                    "Idempotency-Key": "decision-test-1",
                },
                json={
                    "schema_version": "1.0",
                    "decision": "approve",
                    "expected_proposal_version": 1,
                    "comment": "Reviewed for simulation",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "approved_simulation")
        self.assertEqual(decide.call_args.kwargs["actor"].subject, "reviewer-1")
        self.assertEqual(decide.call_args.kwargs["idempotency_key"], "decision-test-1")


if __name__ == "__main__":
    unittest.main()
