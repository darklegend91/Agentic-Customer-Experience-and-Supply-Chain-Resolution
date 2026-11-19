"""Customer investigation API endpoint for remote frontends."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from ...agents.customer_investigation import investigate_customer
from ...db.repositories import (
    RecordNotFound,
    get_customer_orders_readonly,
    get_customer_support_context_readonly,
)
from ...db.session import DatabaseUnavailable
from ...observability.logging import log_safe_error
from ...runtime import LocalDevelopmentOnly
from ..schemas.common import OpaqueId, SchemaModel, TicketMessage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/customers", tags=["customers"])


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
