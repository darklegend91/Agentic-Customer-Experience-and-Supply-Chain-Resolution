"""Local stdio MCP server exposing read-only ticket/order/policy tools."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import uuid4

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from ..api.schemas.evidence import (
    CustomerSupportContextResponse,
    DeliveryEventsResponse,
    OrderInvestigationEvidence,
    OrderSummaryResponse,
    PolicySearchResponse,
    ReturnRefundResponse,
)
from ..api.schemas.ticket import (
    TicketClassification,
    TicketDetailsResponse,
    TicketInvestigationResponse,
)
from ..runtime import require_local_development
from ..tools.customer_context_tools import (
    get_customer_support_context as read_customer_support_context,
)
from ..tools.delivery_tools import (
    get_return_refund_status as read_return_refund_status,
)
from ..tools.delivery_tools import (
    list_delivery_events as read_delivery_events,
)
from ..tools.investigation_tools import investigate_ticket as run_ticket_investigation
from ..tools.order_tools import (
    get_order_investigation as read_order_investigation,
)
from ..tools.order_tools import (
    get_order_summary as read_order_summary,
)
from ..tools.policy_tools import search_policy as run_policy_search
from ..tools.ticket_tools import (
    classify_ticket_message as run_ticket_classification,
)
from ..tools.ticket_tools import (
    get_ticket_details as read_ticket_details,
)
from .schemas import MCPInvestigationInput

mcp = MCPServer("agentic-customer-support-readonly")
READ_ONLY_TOOL = ToolAnnotations(read_only_hint=True, open_world_hint=False)
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"


@mcp.tool(annotations=READ_ONLY_TOOL)
def get_ticket_details(
    ticket_id: Annotated[str, Field(min_length=1, max_length=128, pattern=ID_PATTERN)],
) -> TicketDetailsResponse:
    """Read a ticket's ID, message, and linked order hint from the local fixture."""
    require_local_development()
    return TicketDetailsResponse.model_validate(read_ticket_details(ticket_id))


@mcp.tool(annotations=READ_ONLY_TOOL)
def classify_ticket(
    message: Annotated[str, Field(min_length=1, max_length=5000)],
) -> TicketClassification:
    """Suggest a ticket intent for human review; this does not route or resolve it."""
    require_local_development()
    return TicketClassification.model_validate(run_ticket_classification(message))


@mcp.tool(annotations=READ_ONLY_TOOL)
def get_order_summary(
    order_id: Annotated[str, Field(min_length=1, max_length=128, pattern=ID_PATTERN)],
) -> OrderSummaryResponse:
    """Read an allowlisted order summary and bounded item list from Neon."""
    require_local_development()
    return OrderSummaryResponse.model_validate(read_order_summary(order_id))


@mcp.tool(annotations=READ_ONLY_TOOL)
def get_order_investigation(
    order_id: Annotated[str, Field(min_length=1, max_length=128, pattern=ID_PATTERN)],
) -> OrderInvestigationEvidence:
    """Read order, item, delivery, and return facts in one bounded database snapshot."""
    require_local_development()
    return OrderInvestigationEvidence.model_validate(read_order_investigation(order_id))


@mcp.tool(annotations=READ_ONLY_TOOL)
def list_delivery_events(
    order_id: Annotated[str, Field(min_length=1, max_length=128, pattern=ID_PATTERN)],
    limit: Annotated[int, Field(ge=1, le=100)] = 100,
) -> DeliveryEventsResponse:
    """Read chronological delivery scans for one local fixture order."""
    require_local_development()
    return DeliveryEventsResponse.model_validate(read_delivery_events(order_id, limit=limit))


@mcp.tool(annotations=READ_ONLY_TOOL)
def get_return_refund_status(
    order_id: Annotated[str, Field(min_length=1, max_length=128, pattern=ID_PATTERN)],
    limit: Annotated[int, Field(ge=1, le=50)] = 50,
) -> ReturnRefundResponse:
    """Read recorded return/refund state; does not determine eligibility."""
    require_local_development()
    return ReturnRefundResponse.model_validate(read_return_refund_status(order_id, limit=limit))


@mcp.tool(annotations=READ_ONLY_TOOL)
def get_customer_support_context(
    order_id: Annotated[str, Field(min_length=1, max_length=128, pattern=ID_PATTERN)],
) -> CustomerSupportContextResponse:
    """Read loyalty ledger and prior-contact summaries for an order's customer."""
    require_local_development()
    return CustomerSupportContextResponse.model_validate(read_customer_support_context(order_id))


@mcp.tool(annotations=READ_ONLY_TOOL)
def search_policy(
    query: Annotated[str, Field(min_length=3, max_length=3000)],
    top_k: Annotated[int, Field(ge=1, le=10)] = 3,
    methods: Annotated[list[Literal["semantic", "keyword"]], Field(min_length=1, max_length=2)] | None = None,
    locale: Annotated[str, Field(min_length=5, max_length=8, pattern=r"^[a-z]{2}-[A-Z]{2}$")] = "en-IN",
) -> PolicySearchResponse:
    """Search versioned synthetic draft passages; these are not approved policy."""
    require_local_development()
    if methods is not None and len(set(methods)) != len(methods):
        raise ValueError("methods must not contain duplicates")
    return PolicySearchResponse.model_validate(run_policy_search(query, top_k=top_k, methods=methods, locale=locale))


@mcp.tool(annotations=READ_ONLY_TOOL)
def investigate_ticket(
    request: MCPInvestigationInput,
) -> TicketInvestigationResponse:
    """Combine review-only triage with separate order and policy evidence."""
    require_local_development()
    result = run_ticket_investigation(**request.model_dump())
    return TicketInvestigationResponse.model_validate({"request_id": str(uuid4()), **result})


def main() -> None:
    """Run over stdio for a local MCP host such as Claude Desktop or Inspector."""
    require_local_development()
    try:
        mcp.run()
    finally:
        from ..tools.policy_tools import close_policy_retrievers

        close_policy_retrievers()


if __name__ == "__main__":
    main()
