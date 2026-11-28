"""Customer investigation API endpoint for remote frontends."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, model_validator

from ...agents.customer_investigation import investigate_customer
from ...approval.permissions import WorkflowActor, authorize_order, authorize_resource_scope, require_support
from ...db.repositories import (
    RecordNotFound,
    get_chat_anchor_readonly,
    get_chat_relationships_readonly,
    get_customer_orders_readonly,
    get_customer_support_context_readonly,
    get_order_investigation_readonly,
)
from ...db.session import DatabaseUnavailable
from ...guardrails.content_safety import UnsafeContentError, require_safe_evidence
from ...observability.logging import log_safe_error
from ...runtime import LocalDevelopmentOnly
from ..schemas.common import OpaqueId, SchemaModel, TicketMessage
from ..schemas.evidence import OrderInvestigationEvidence

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/customers", tags=["customers"])


class ChatContextRequest(SchemaModel):
    ticket_id: OpaqueId | None = None
    order_id: OpaqueId | None = None
    customer_id: OpaqueId | None = None
    include_order_details: bool = False

    @model_validator(mode="after")
    def require_reference(self):
        if not (self.ticket_id or self.order_id or self.customer_id):
            raise ValueError("Provide a ticket ID, order ID, or customer ID")
        return self


class ChatCustomerProfile(SchemaModel):
    loyalty_tier: str | None
    preferred_language: str | None
    account_created_date: str | None


class ChatOrderReference(SchemaModel):
    order_id: OpaqueId
    order_date: str | None
    status: str | None


class ChatTicketReference(SchemaModel):
    ticket_id: OpaqueId
    order_id: OpaqueId | None


class ChatContextResponse(SchemaModel):
    ticket_id: OpaqueId | None
    order_id: OpaqueId | None
    customer_id: OpaqueId | None
    customer: ChatCustomerProfile | None
    orders: list[ChatOrderReference]
    tickets: list[ChatTicketReference]
    order_details: OrderInvestigationEvidence | None = None


@router.post("/chat-context", response_model=ChatContextResponse, response_model_exclude_unset=True)
def read_chat_context(
    request: ChatContextRequest,
    http_request: Request,
    actor: WorkflowActor = Depends(require_support),
) -> dict:
    """Connect a verified reference to the records visible to this support actor."""
    references = request.model_dump(exclude={"include_order_details"})
    authorize_resource_scope(actor, references)
    try:
        anchor = get_chat_anchor_readonly(**references)
        order_id = anchor["order_id"]
        customer_id = anchor["customer_id"]
        if request.customer_id and request.customer_id != customer_id:
            raise HTTPException(status_code=403, detail="Record is outside the active customer context")
        if request.order_id and request.order_id != order_id:
            raise HTTPException(status_code=422, detail="The ticket and order IDs do not match the same record")
        if order_id:
            authorize_order(actor, order_id)
        if "*" not in actor.allowed_customer_ids and customer_id not in actor.allowed_customer_ids:
            customer_id = None
        related = get_chat_relationships_readonly(
            order_id=order_id,
            customer_id=customer_id,
            allowed_order_ids=actor.allowed_order_ids,
            allowed_ticket_ids=actor.allowed_ticket_ids,
        )
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (DatabaseUnavailable, LocalDevelopmentOnly) as exc:
        raise HTTPException(status_code=503, detail="Related records are temporarily unavailable") from exc
    if order_id and not any(row["order_id"] == order_id for row in related["orders"]):
        raise HTTPException(status_code=409, detail="The order changed during lookup. Please try again.")
    if ticket_id := anchor["ticket_id"]:
        ticket = {"ticket_id": ticket_id, "order_id": order_id}
        if not order_id:
            related["tickets"].append(ticket)
        elif ticket not in related["tickets"]:
            raise HTTPException(status_code=409, detail="The ticket changed during lookup. Please try again.")
    result = {**anchor, **related, "customer_id": customer_id}
    if request.include_order_details:
        result["order_details"] = None
        detail_order = order_id
        if not detail_order and len(related["orders"]) == 1:
            detail_order = related["orders"][0]["order_id"]
        if detail_order:
            authorize_order(actor, detail_order)
            try:
                details = get_order_investigation_readonly(detail_order, customer_id=customer_id)
                require_safe_evidence(details)
                result["order_details"] = details
            except RecordNotFound as exc:
                raise HTTPException(status_code=409, detail="The order changed during lookup. Please try again.") from exc
            except (DatabaseUnavailable, LocalDevelopmentOnly, UnsafeContentError) as exc:
                log_safe_error(
                    logger, event="chat_order_details_unavailable",
                    request_id=getattr(http_request.state, "request_id", "unavailable"),
                    stage="order_lookup", error_type=type(exc).__name__,
                )
    return result


class CustomerInvestigationRequest(SchemaModel):
    customer_id: OpaqueId
    message: TicketMessage
    ticket_id: OpaqueId | None = None
    allowed_customer_ids: list[str] = Field(default_factory=lambda: ["*"])


@router.get("/{customer_id}/orders")
def read_customer_orders(customer_id: str, http_request: Request) -> dict:
    """Read bounded customer order history from the database."""
    try:
        return get_customer_orders_readonly(customer_id.strip().upper())
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (DatabaseUnavailable, LocalDevelopmentOnly) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log_safe_error(
            logger,
            event="customer_orders_lookup_failed",
            request_id=http_request.state.request_id,
            stage="customer_lookup",
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=503, detail="Customer orders lookup failed") from exc


@router.get("/{customer_id}/context")
def read_customer_context(customer_id: str, http_request: Request) -> dict:
    """Read customer loyalty account, transaction ledger, and prior communications."""
    try:
        return get_customer_support_context_readonly(customer_id=customer_id.strip().upper())
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (DatabaseUnavailable, LocalDevelopmentOnly) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log_safe_error(
            logger,
            event="customer_context_lookup_failed",
            request_id=http_request.state.request_id,
            stage="customer_lookup",
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=503, detail="Customer context lookup failed") from exc


@router.post("/investigate")
def investigate(request: CustomerInvestigationRequest, http_request: Request) -> dict:
    """Run the customer investigation specialist and return structured results."""
    try:
        result = investigate_customer({
            "customer_id": request.customer_id,
            "message": request.message,
            "ticket_id": request.ticket_id,
            "allowed_customer_ids": request.allowed_customer_ids,
        })
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (DatabaseUnavailable, LocalDevelopmentOnly) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        log_safe_error(
            logger,
            event="customer_investigation_failed",
            request_id=http_request.state.request_id,
            stage="customer_investigation",
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=503, detail="Customer investigation dependency unavailable") from exc
    return {"request_id": http_request.state.request_id, **result}
