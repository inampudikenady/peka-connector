from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    certificates,
    cmdb,
    diagnostics,
    documents,
    health,
    integrations,
    inventory,
    knowledge,
    loki,
    operations,
    plugins,
    prometheus,
    servicenow,
    settings,
    sources,
    users,
    zammad,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(plugins.router, prefix="/plugins", tags=["plugins"])
api_router.include_router(sources.router, prefix="/sources", tags=["sources"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(cmdb.router, prefix="/cmdb", tags=["cmdb"])
api_router.include_router(prometheus.router, prefix="/prometheus", tags=["prometheus"])
api_router.include_router(loki.router, prefix="/loki", tags=["loki"])
api_router.include_router(zammad.router, prefix="/zammad", tags=["zammad"])
api_router.include_router(servicenow.router, prefix="/servicenow", tags=["servicenow"])
api_router.include_router(integrations.router, prefix="/integrations", tags=["integrations"])
api_router.include_router(inventory.router, prefix="/inventory", tags=["inventory"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(operations.router, tags=["operations"])
api_router.include_router(diagnostics.router, prefix="/diagnostics", tags=["diagnostics"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(
    certificates.router, prefix="/settings/certificates", tags=["settings", "certificates"]
)
