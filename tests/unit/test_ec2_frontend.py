"""Check the real Streamlit request boundary without contacting external APIs."""

import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import httpx
import streamlit as st
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from backend.app.api.schemas.ticket import TicketInvestigationRequest


APP = Path(__file__).resolve().parents[2] / "frontend" / "app.py"
API = "https://support.example"


class Ec2FrontendTests(unittest.TestCase):
    def setUp(self):
        st.cache_resource.clear()
        self.requests = []
        self.client = Mock()
        self.client.request.side_effect = self.respond
        self.client_patch = patch("httpx.Client", return_value=self.client)
        self.client_patch.start()
        self.env_patch = patch.dict(os.environ, {
            "API_BASE_URL": API, "API_BASE_URL_LOCKED": "false",
            "ALLOW_REMOTE_API": "true", "GROQ_API_KEY": "",
        })
        self.env_patch.start()
        self.app = AppTest.from_file(APP, default_timeout=15)
        self.app.secrets.update({
            "API_BASE_URL": API, "DEMO_API_TOKEN": "test-demo-token",
            "WORKFLOW_API_TOKEN": "test-support-token",
            "WORKFLOW_REVIEWER_TOKEN": "test-reviewer-token",
            "GROQ_API_KEY": "",
        })
        self.app.run()
        self.assertFalse(self.app.exception)

    def tearDown(self):
        self.client_patch.stop()
        self.env_patch.stop()
        st.cache_resource.clear()

    def respond(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if url.endswith("/health"):
            body = {"status": "ok"}
        elif url.endswith("/tickets/investigate"):
            body = {"classification": {"intent": "damaged_item", "confidence": 0.9,
                    "classifier_provider": "laya"}, "policy_evidence": {"results": {}}}
        else:
            raise AssertionError("Unexpected request: " + url)
        return httpx.Response(200, json=body, request=httpx.Request(method, url))

    def check_health(self):
        next(button for button in self.app.sidebar.button if button.label == "Check API health").click().run()
        self.assertFalse(self.app.exception)
        return self.requests[-1][2]["headers"]

    def test_chat_payload_satisfies_backend_contract(self):
        self.app.chat_input[0].set_value("My order arrived damaged").run()
        self.assertFalse(self.app.exception)
        request = next(item for item in self.requests if item[1].endswith("/tickets/investigate"))
        try:
            validated = TicketInvestigationRequest.model_validate(request[2]["json"])
        except ValidationError as exc:
            self.fail("Chat request violates the backend contract: " + str(exc))
        self.assertEqual(validated.schema_version, "1.0")

    def test_configured_https_endpoint_receives_demo_token(self):
        headers = self.check_health()
        self.assertEqual(headers.get("X-Demo-Token"), "test-demo-token")

    def test_other_endpoint_does_not_receive_demo_token(self):
        self.app.text_input(key="api_base_url").set_value("https://unrelated.example").run()
        headers = self.check_health()
        self.assertNotIn("X-Demo-Token", headers)

    def test_plain_http_endpoint_does_not_receive_demo_token(self):
        self.app.text_input(key="api_base_url").set_value("http://support.example").run()
        headers = self.check_health()
        self.assertNotIn("X-Demo-Token", headers)


if __name__ == "__main__":
    unittest.main()
