from fastapi import APIRouter

from app.api.schemas import HealthResponse
from app.core.version import CONNECTOR_VERSION

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(version=CONNECTOR_VERSION)
