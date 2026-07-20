from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    diagnostics,
    health,
    operations,
    plugins,
    settings,
    sources,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(plugins.router, prefix="/plugins", tags=["plugins"])
api_router.include_router(sources.router, prefix="/sources", tags=["sources"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(operations.router, tags=["operations"])
api_router.include_router(diagnostics.router, prefix="/diagnostics", tags=["diagnostics"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
