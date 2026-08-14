from fastapi import APIRouter

from app.api.dependencies import CurrentUser, KnowledgeServiceDep
from app.api.schemas import (
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSearchResultResponse,
    KnowledgeStatsResponse,
)

router = APIRouter()


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    request: KnowledgeSearchRequest,
    _: CurrentUser,
    knowledge: KnowledgeServiceDep,
) -> KnowledgeSearchResponse:
    results = await knowledge.search(request.query, request.top_k, request.document_id)
    return KnowledgeSearchResponse(
        results=[
            KnowledgeSearchResultResponse(
                document_id=result.document_id,
                chunk_id=result.chunk_id,
                content=result.content,
                score=result.score,
                source=result.source,
                metadata=result.metadata,
            )
            for result in results
        ]
    )


@router.get("/stats", response_model=KnowledgeStatsResponse)
async def knowledge_stats(_: CurrentUser, knowledge: KnowledgeServiceDep) -> KnowledgeStatsResponse:
    health = await knowledge.health_status()
    if not health.qdrant_reachable or not health.collection_available:
        return KnowledgeStatsResponse(
            status="unavailable",
            document_count=0,
            indexed_chunk_count=0,
            qdrant_reachable=health.qdrant_reachable,
            collection_available=health.collection_available,
            documents_stored=False,
            vectors_stored=False,
            search_operational=False,
            engine_version=health.engine_version,
            collection=knowledge.settings.qdrant_collection,
            statistics_readable=health.statistics_readable,
        )
    stats = await knowledge.stats()
    return KnowledgeStatsResponse(
        status="healthy" if stats.search_operational else "degraded",
        document_count=stats.document_count,
        indexed_chunk_count=stats.indexed_chunk_count,
        pending_count=stats.pending_count,
        failed_count=stats.failed_count,
        last_index_activity=stats.last_index_activity,
        qdrant_reachable=stats.qdrant_reachable,
        collection_available=stats.collection_available,
        documents_stored=stats.documents_stored,
        vectors_stored=stats.vectors_stored,
        search_operational=stats.search_operational,
        last_search_success=stats.last_search_success,
        last_search_at=stats.last_search_at,
        engine_version=stats.engine_version,
        collection=knowledge.settings.qdrant_collection,
        statistics_readable=stats.statistics_readable,
    )
