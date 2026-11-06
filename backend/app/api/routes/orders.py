"""Read-only order endpoints over the local Neon fixture."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Path, Query, Request

from ...db.repositories import RecordNotFound
from ...db.session import DatabaseUnavailable
from ...observability.logging import log_safe_error
from ...runtime import LocalDevelopmentOnly
from ...tools.delivery_tools import get_return_refund_status, list_delivery_events
from ...tools.customer_context_tools import get_customer_support_context
from ...tools.order_tools import get_order_investigation, get_order_summary
from ..schemas.common import OpaqueId
from ..schemas.evidence import (
    CustomerSupportContextResponse,
    DeliveryEventsResponse,
    OrderInvestigationEvidence,
    OrderSummaryResponse,
    ReturnRefundResponse,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/orders", tags=["orders"])


def _read(call, *, not_found: str, request_id: str):
    try:
        result = call()
        if isinstance(result, dict) and result.get("status") == "not_found":
            raise HTTPException(status_code=404, detail=not_found)
        return result
    except HTTPException:
        raise
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail=not_found) from exc
    except (DatabaseUnavailable, LocalDevelopmentOnly) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        log_safe_error(logger, event="order_evidence_lookup_failed", request_id=request_id, stage="order_lookup", error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="Order evidence source unavailable") from exc


@router.get("/{order_id}/summary", response_model=OrderSummaryResponse)
def order_summary(http_request: Request, order_id: OpaqueId = Path(...)) -> dict:
    return _read(lambda: get_order_summary(order_id), not_found="Order was not found in the development fixture", request_id=http_request.state.request_id)


@router.get("/{order_id}/investigation", response_model=OrderInvestigationEvidence)
def order_investigation(http_request: Request, order_id: OpaqueId = Path(...)) -> dict:
    """Fetch order, items, delivery events, and returns with one bounded SQL statement."""
    return _read(
        lambda: get_order_investigation(order_id),
        not_found="Order was not found in the development fixture",
        request_id=http_request.state.request_id,
    )


@router.get("/{order_id}/delivery-events", response_model=DeliveryEventsResponse)
def delivery_events(
    http_request: Request,
    order_id: OpaqueId = Path(...),
    limit: int = Query(default=100, ge=1, le=100),
) -> dict:
    return _read(lambda: list_delivery_events(order_id, limit=limit), not_found="Order was not found in the development fixture", request_id=http_request.state.request_id)


@router.get("/{order_id}/returns-refunds", response_model=ReturnRefundResponse)
def return_refund_status(
    http_request: Request,
    order_id: OpaqueId = Path(...),
    limit: int = Query(default=50, ge=1, le=50),
) -> dict:
    return _read(lambda: get_return_refund_status(order_id, limit=limit), not_found="Order was not found in the development fixture", request_id=http_request.state.request_id)


@router.get("/{order_id}/customer-context", response_model=CustomerSupportContextResponse)
def customer_support_context(http_request: Request, order_id: OpaqueId = Path(...)) -> dict:
    """Read loyalty events and prior communication summaries scoped to one order."""
    return _read(
        lambda: get_customer_support_context(order_id),
        not_found="Order was not found in the development fixture",
        request_id=http_request.state.request_id,
    )
