"""Verify relationship lookup permissions at the HTTP boundary."""

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes.customers import router
from backend.app.approval.permissions import WorkflowActor, require_support
from backend.app.db.session import DatabaseUnavailable
from tests.agents.test_day5_workflow import order_evidence


PATH = "/customers/chat-context"
CUSTOMER = "CUS-0844BCE290"
ORDER = "ORD-ID-a15d80b929"
TICKET = "T-100"


class ChatContextApiTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.client = self.enterContext(TestClient(self.app))
        repository = "backend.app.api.routes.customers."
        self.anchor = self.enterContext(patch(repository + "get_chat_anchor_readonly"))
        self.related = self.enterContext(patch(repository + "get_chat_relationships_readonly"))
        self.details = self.enterContext(patch(repository + "get_order_investigation_readonly", create=True))
        self.anchor.return_value = {"ticket_id": TICKET, "order_id": ORDER, "customer_id": CUSTOMER}
        self.related.return_value = {
            "customer": {"loyalty_tier": "Silver", "preferred_language": "en", "account_created_date": None},
            "orders": [{"order_id": ORDER, "status": "delivered", "order_date": None}],
            "tickets": [{"ticket_id": TICKET, "order_id": ORDER}],
        }

    def set_scope(self, *, orders=(ORDER,), tickets=(TICKET,), customers=(CUSTOMER,)):
        actor = WorkflowActor("support", frozenset({"support_agent"}), frozenset(orders),
                              frozenset(tickets), allowed_customer_ids=frozenset(customers))
        self.app.dependency_overrides[require_support] = lambda: actor

    def test_authentication_is_required_before_any_lookup(self):
        response = self.client.post(PATH, json={"ticket_id": TICKET})
        self.assertEqual(response.status_code, 401)
        self.anchor.assert_not_called()

    def test_related_records_are_queried_only_within_the_actors_scope(self):
        self.set_scope()
        response = self.client.post(PATH, json={"ticket_id": TICKET})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["tickets"], [{"ticket_id": TICKET, "order_id": ORDER}])
        self.assertEqual(response.json()["customer_id"], CUSTOMER)
        self.related.assert_called_once_with(order_id=ORDER, customer_id=CUSTOMER,
                                            allowed_order_ids=frozenset({ORDER}), allowed_ticket_ids=frozenset({TICKET}))
        self.details.assert_not_called()

    def test_requested_order_details_are_read_for_the_verified_order_and_customer(self):
        self.set_scope()
        evidence = order_evidence()
        evidence["order_id"] = evidence["order"]["order_id"] = ORDER
        self.details.return_value = evidence

        response = self.client.post(PATH, json={"ticket_id": TICKET, "include_order_details": True})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["order_details"]["items"][0]["product_name"], "Mixer grinder")
        self.details.assert_called_once_with(ORDER, customer_id=CUSTOMER)

    def test_failed_order_details_lookup_leaves_the_verified_order_list_available(self):
        self.set_scope()
        self.details.side_effect = DatabaseUnavailable("fixture error")

        response = self.client.post(PATH, json={"ticket_id": TICKET, "include_order_details": True})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["order_details"])
        self.assertEqual(len(response.json()["orders"]), 1)

    def test_ticket_outside_active_customer_ends_at_anchor_lookup(self):
        self.set_scope(customers=("*",))
        response = self.client.post(PATH, json={"ticket_id": TICKET, "customer_id": "CUS-0097A0C5B0"})
        self.assertEqual(response.status_code, 403, response.text)
        self.related.assert_not_called()
        self.assertNotIn(CUSTOMER, response.text)

    def test_ticket_cannot_expand_to_an_order_outside_actor_scope(self):
        self.set_scope(orders=())
        response = self.client.post(PATH, json={"ticket_id": TICKET, "include_order_details": True})
        self.assertEqual(response.status_code, 403, response.text)
        self.related.assert_not_called()
        self.details.assert_not_called()
        self.assertNotIn(ORDER, response.text)

    def test_unpermitted_ticket_is_rejected_before_any_lookup(self):
        self.set_scope(tickets=())
        response = self.client.post(PATH, json={"ticket_id": TICKET})
        self.assertEqual(response.status_code, 403, response.text)
        self.anchor.assert_not_called()

    def test_mismatched_ticket_and_order_cannot_be_combined(self):
        self.set_scope(orders=("*",))
        response = self.client.post(PATH, json={"ticket_id": TICKET, "order_id": "ORD-ID-0123456789"})
        self.assertEqual(response.status_code, 422, response.text)
        self.related.assert_not_called()

    def test_order_only_scope_omits_the_customers_account_data(self):
        self.set_scope(customers=())
        self.anchor.return_value["ticket_id"] = None
        self.related.return_value["customer"] = None
        response = self.client.post(PATH, json={"order_id": ORDER})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["customer_id"])
        self.related.assert_called_once_with(order_id=ORDER, customer_id=None,
                                            allowed_order_ids=frozenset({ORDER}), allowed_ticket_ids=frozenset({TICKET}))
