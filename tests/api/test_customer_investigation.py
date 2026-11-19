from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.agents.graph import build_workflow_graph
from backend.app.agents.graph import _safe_summary
from backend.app.approval.permissions import WorkflowActor, get_workflow_actor
from backend.app.approval.service import get_workflow_response
from backend.app.main import app


CUSTOMER = "CUS-A0AB74C303"
OTHER = "CUS-8516C1E29C"
ORDER = "ORD-ID-example1"


def actor(*customer_ids):
    return WorkflowActor(
        subject="tester",
        roles=frozenset({"support_agent"}),
        allowed_order_ids=frozenset({ORDER}),
        allowed_ticket_ids=frozenset(),
        allowed_customer_ids=frozenset(customer_ids),
    )


def test_customer_id_alone_reaches_langgraph_and_answers_with_cited_records():
    graph = build_workflow_graph(persistence_enabled=False)
    recorded = {}

    def execute(state):
        recorded.update(graph.invoke(state))

    def investigate(body):
        with TestClient(app) as client:
            return client.post("/workflows", json={"schema_version": "1.0", **body})

    snapshot = {
        "as_of": "2026-11-19T10:00:00Z",
        "has_more_orders": False,
        "orders": [{"order_id": ORDER, "status": "delivered", "order_date": "2026-11-17"}],
    }
    context = {
        "status": "found", "as_of": snapshot["as_of"],
        "loyalty_account": {"account_id": "account-1", "points_balance": 420, "as_of": snapshot["as_of"]},
        "prior_communications": [], "loyalty_transactions": [], "missing_fields": [], "conflicts": [],
        "evidence_refs": {"loyalty_account": ["loyalty_account:account-1"], "customer_context_lookup": ["customer_context:lookup"]},
    }
    with (
        patch.dict(app.dependency_overrides, {get_workflow_actor: lambda: actor(CUSTOMER)}),
        patch("backend.app.approval.service.create_workflow_run") as persist,
        patch("backend.app.api.routes.workflows.execute_workflow", side_effect=execute),
        patch("backend.app.agents.customer_investigation.get_customer_orders_readonly", return_value=snapshot),
        patch("backend.app.agents.customer_investigation.get_customer_support_context_readonly", return_value=context),
        patch("backend.app.agents.triage.classify_ticket_message") as classify,
    ):
        for body in ({"customer_id": CUSTOMER}, {"message": f"Tell me about {CUSTOMER.lower()}"}):
            assert investigate(body).status_code == 202
            assert persist.call_args.kwargs["customer_id"] == CUSTOMER
            assert recorded["specialist"] == "customer_investigation"
            assert recorded["status"] == "answer_ready"
            assert "delivered" in recorded["answer"]
            assert "420 points" in recorded["answer"]
            assert f"order:{ORDER}" in recorded["evidence_refs"]
            assert recorded["order_id"] is None
            response = get_workflow_response(recorded["workflow_id"], row={
                "workflow_id": recorded["workflow_id"],
                "thread_id": recorded["thread_id"],
                "status": recorded["status"],
                "summary_json": _safe_summary(recorded),
            })
            assert response["status"] == "answer_ready"
            assert response["classification"] is None
        classify.assert_not_called()


def test_customer_scope_is_checked_before_queuing_and_reading():
    workflow_id = "11111111-1111-4111-8111-111111111111"
    with (
        patch.dict(app.dependency_overrides, {get_workflow_actor: lambda: actor(CUSTOMER)}),
        patch("backend.app.approval.service.create_workflow_run") as persist,
        patch("backend.app.api.routes.workflows.get_workflow", return_value={"created_by": "tester", "customer_id": OTHER}),
        patch("backend.app.api.routes.workflows.get_workflow_trace") as trace,
        TestClient(app) as client,
    ):
        header = {"schema_version": "1.0"}
        assert client.post("/workflows", json={**header, "customer_id": OTHER}).status_code == 403
        assert client.post("/workflows", json={**header, "message": OTHER}).status_code == 403
        assert client.post("/workflows", json={**header, "customer_id": CUSTOMER, "message": OTHER}).status_code == 422
        for suffix in ("", "/trace", "/snapshot", "/events"):
            assert client.get(f"/workflows/{workflow_id}{suffix}").status_code == 403
        persist.assert_not_called()
        trace.assert_not_called()


def test_customer_scoped_requests_clarify_order_specific_cases_without_tools():
    graph = build_workflow_graph(persistence_enabled=False)
    state = {"workflow_id": "customer-test", "customer_id": CUSTOMER, "allowed_customer_ids": [CUSTOMER]}
    with patch("backend.app.agents.customer_investigation.get_customer_orders_readonly") as lookup:
        result = graph.invoke({**state, "message": "Where is my refund?"})
        assert result["status"] == "needs_information"
        assert result["missing_information"] == ["order_id"]
        blocked = graph.invoke({**state, "input_error_code": "unsafe_input"})
        assert blocked["status"] == "escalated"
        lookup.assert_not_called()


def test_mismatched_customer_and_order_never_returns_order_evidence():
    graph = build_workflow_graph(persistence_enabled=False)
    state = {
        "workflow_id": "customer-test", "message": "Order status", "order_id": ORDER,
        "customer_id": CUSTOMER, "allowed_customer_ids": [CUSTOMER], "allowed_order_ids": [ORDER],
    }
    triage = {"classification": {"intent": "order_status"}, "triage_ready": True}
    with (
        patch("backend.app.agents.graph.triage_ticket", return_value=triage),
        patch("backend.app.agents.investigation.order_belongs_to_customer", return_value=False),
        patch("backend.app.agents.investigation.get_order_investigation") as order_lookup,
    ):
        result = graph.invoke(state)
        assert result["status"] == "needs_information"
        assert result["reason_codes"] == ["customer_order_reference_conflict"]
        order_lookup.assert_not_called()
