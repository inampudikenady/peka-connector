from fastapi import APIRouter

from app.api.dependencies import KnowledgeServiceDep
from app.api.schemas import ComponentHealth, ComponentVersionResponse, HealthResponse
from app.core.version import CONNECTOR_VERSION

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(knowledge: KnowledgeServiceDep) -> HealthResponse:
    try:
        store = await knowledge.health_status()
        knowledge_status = (
            "unavailable"
            if not store.qdrant_reachable
            else "healthy"
            if store.collection_available and store.statistics_readable
            else "degraded"
        )
    except Exception:
        knowledge_status = "unavailable"
    return HealthResponse(
        status="healthy" if knowledge_status == "healthy" else "degraded",
        version=CONNECTOR_VERSION,
        components={
            "connector": ComponentHealth(status="healthy"),
            "local_knowledge_store": ComponentHealth(status=knowledge_status),
        },
    )


@router.get("/version", response_model=ComponentVersionResponse)
async def version(knowledge: KnowledgeServiceDep) -> ComponentVersionResponse:
    try:
        qdrant_version = (await knowledge.health_status()).engine_version or "Unknown"
    except Exception:
        qdrant_version = "Unknown"
    return ComponentVersionResponse(
        peka_connector=CONNECTOR_VERSION,
        components={"qdrant": qdrant_version},
    )
