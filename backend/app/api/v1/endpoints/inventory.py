from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.api.dependencies import Administrator, CurrentUser, InventoryServiceDep, OperationsDep

router = APIRouter()


class CorrelationDecisionRequest(BaseModel):
    asset_id: UUID | None = None
    status: str


@router.get("")
async def assets(
    _: CurrentUser,
    service: InventoryServiceDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    search: str | None = Query(default=None, max_length=500),
    coverage: str | None = None,
    environment: str | None = Query(default=None, max_length=255),
    asset_type: str | None = Query(default=None, max_length=255),
    lifecycle_status: str | None = Query(default=None, max_length=100),
    prometheus_health: str | None = None,
    correlation_status: str | None = None,
) -> dict[str, object]:
    items, total = await service.list_assets(
        page,
        page_size,
        search,
        coverage,
        environment,
        asset_type,
        lifecycle_status,
        prometheus_health,
        correlation_status,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{asset_id}")
async def detail(asset_id: UUID, _: CurrentUser, service: InventoryServiceDep) -> dict[str, object]:
    result = await service.asset_detail(asset_id)
    if not result:
        raise HTTPException(status_code=404, detail="Inventory asset not found")
    return result


@router.post("/observations/{observation_id}/correlation")
async def decide(
    observation_id: UUID,
    request: CorrelationDecisionRequest,
    actor: Administrator,
    service: InventoryServiceDep,
    operations: OperationsDep,
) -> dict[str, object]:
    allowed = {"matched", "rejected", "split"}
    if request.status not in allowed:
        raise HTTPException(status_code=422, detail="Unsupported correlation decision")
    try:
        result = await service.manual_decision(
            observation_id, request.asset_id, request.status, actor.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    correlation_id = str(uuid4())
    await operations.record_event(
        "inventory.manual_correlation_changed",
        f"Manual correlation changed to {request.status}",
        actor=actor,
        target_type="inventory_observation",
        target_id=str(observation_id),
        details={
            "correlation_id": correlation_id,
            "asset_id": str(request.asset_id) if request.asset_id else None,
            "status": request.status,
        },
        component="inventory",
    )
    return {"id": result.id, "status": result.status, "correlation_id": correlation_id}
