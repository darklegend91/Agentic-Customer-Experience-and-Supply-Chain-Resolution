"""Non-sensitive loyalty integration readiness endpoint."""

from fastapi import APIRouter

from ...loyalty.provider import provider_status


router = APIRouter(prefix="/loyalty", tags=["loyalty"])


@router.get("/provider-status")
def read_provider_status() -> dict:
    """Expose configuration readiness without endpoint URLs or credentials."""
    return provider_status()
