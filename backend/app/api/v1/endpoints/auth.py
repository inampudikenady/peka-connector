from fastapi import APIRouter

from app.api.dependencies import AuthServiceDep, CurrentUser
from app.api.schemas import LoginRequest, TokenResponse

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, service: AuthServiceDep) -> TokenResponse:
    token = await service.authenticate(request.username, request.password)
    return TokenResponse(access_token=token)


@router.get("/me")
async def me(user: CurrentUser) -> dict[str, str]:
    return {"id": str(user.id), "username": user.username}
