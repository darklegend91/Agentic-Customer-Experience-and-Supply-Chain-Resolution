"""Read-only search over development draft policy evidence."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from ...runtime import LocalDevelopmentOnly
from ...observability.logging import log_safe_error
from ...tools.policy_tools import search_policy
from ..schemas.ticket import PolicySearchRequest
from ..schemas.evidence import PolicySearchResponse


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/policies", tags=["policies"])


@router.post("/search", response_model=PolicySearchResponse)
def policy_search(request: PolicySearchRequest, http_request: Request) -> dict:
    try:
        return search_policy(request.query, top_k=request.top_k, methods=request.methods, locale=request.locale)
    except (LocalDevelopmentOnly, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Policy retrieval configuration unavailable") from exc
    except Exception as exc:
        log_safe_error(logger, event="policy_search_failed", request_id=http_request.state.request_id, stage="policy_retrieval", error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="Policy retrieval dependency unavailable") from exc
