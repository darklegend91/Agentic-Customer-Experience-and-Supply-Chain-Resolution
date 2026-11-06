"""Non-sensitive process health endpoint."""

from fastapi import APIRouter

from ...api.schemas.common import SchemaModel


router = APIRouter(tags=["health"])


class HealthResponse(SchemaModel):
    status: str
    service: str
    environment: str


@router.get("/health", response_model=HealthResponse)
def health() -> dict[str, str]:
    return {"status": "ok", "service": "agentic-customer-support", "environment": "development-only"}
