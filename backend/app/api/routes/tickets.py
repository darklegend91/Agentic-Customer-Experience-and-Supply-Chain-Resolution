"""Ticket read, triage, and investigation API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Path, Request

from ...db.repositories import RecordNotFound
from ...db.session import DatabaseUnavailable
from ...observability.logging import log_safe_error
from ...runtime import LocalDevelopmentOnly
from ...tools.investigation_tools import investigate_ticket
from ...tools.ticket_tools import classify_ticket_message, get_ticket_details
from ..schemas.common import OpaqueId
from ..schemas.ticket import (
    TicketClassificationResponse,
    TicketClassifyRequest,
    TicketDetailsResponse,
    TicketInvestigationRequest,
    TicketInvestigationResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("/classify", response_model=TicketClassificationResponse)
def classify(request: TicketClassifyRequest, http_request: Request) -> dict:
    try:
        result = classify_ticket_message(request.message)
    except (LocalDevelopmentOnly, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        log_safe_error(logger, event="ticket_classification_failed", request_id=http_request.state.request_id, stage="classification", error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="Ticket classifier unavailable") from exc
    return {"request_id": http_request.state.request_id, "classification": result}


@router.post("/investigate", response_model=TicketInvestigationResponse)
def investigate(request: TicketInvestigationRequest, http_request: Request) -> dict:
    try:
        result = investigate_ticket(**request.model_dump(exclude={"schema_version"}))
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (DatabaseUnavailable, LocalDevelopmentOnly) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        log_safe_error(logger, event="ticket_investigation_failed", request_id=http_request.state.request_id, stage="investigation", error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="Ticket investigation dependency unavailable") from exc
    return {"request_id": http_request.state.request_id, **result}


@router.get("/{ticket_id}", response_model=TicketDetailsResponse)
def get_ticket(http_request: Request, ticket_id: OpaqueId = Path(...)) -> dict:  # noqa: B008
    try:
        result = get_ticket_details(ticket_id)
        if result.get("status") == "not_found":
            raise HTTPException(status_code=404, detail="Ticket was not found in the development fixture")
        return result
    except HTTPException:
        raise
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (DatabaseUnavailable, LocalDevelopmentOnly) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log_safe_error(logger, event="ticket_lookup_failed", request_id=http_request.state.request_id, stage="ticket_lookup", error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="Ticket lookup unavailable") from exc
