"""Investigation API alias for clients organized around investigations."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from ...db.repositories import RecordNotFound
from ...db.session import DatabaseUnavailable
from ...observability.logging import log_safe_error
from ...runtime import LocalDevelopmentOnly
from ...tools.investigation_tools import investigate_ticket
from ..schemas.ticket import TicketInvestigationRequest, TicketInvestigationResponse


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.post("/tickets", response_model=TicketInvestigationResponse)
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
