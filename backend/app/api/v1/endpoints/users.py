from uuid import UUID

from fastapi import APIRouter, status

from app.api.dependencies import Administrator, OperationsDep, UserServiceDep
from app.api.schemas import (
    UserCreateRequest,
    UserResetPasswordRequest,
    UserResponse,
    UserStateRequest,
)

router = APIRouter()


@router.get("", response_model=list[UserResponse])
async def list_users(_: Administrator, service: UserServiceDep) -> object:
    return await service.list_users()


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: UserCreateRequest,
    actor: Administrator,
    service: UserServiceDep,
    operations: OperationsDep,
) -> object:
    user = await service.create_user(
        request.username, request.password, request.role, request.enabled
    )
    await operations.record_event(
        "user.created",
        f"User {user.username} created with role {user.role}",
        actor=actor,
        target_type="user",
        target_id=str(user.id),
        component="users",
    )
    return user


@router.put("/{user_id}/state", response_model=UserResponse)
async def set_user_state(
    user_id: UUID,
    request: UserStateRequest,
    actor: Administrator,
    service: UserServiceDep,
    operations: OperationsDep,
) -> object:
    user = await service.set_active(user_id, request.enabled, actor.id)
    action = "enabled" if request.enabled else "disabled"
    await operations.record_event(
        f"user.{action}",
        f"User {user.username} {action}",
        actor=actor,
        target_type="user",
        target_id=str(user.id),
        component="users",
    )
    return user


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: UUID,
    request: UserResetPasswordRequest,
    actor: Administrator,
    service: UserServiceDep,
    operations: OperationsDep,
) -> None:
    await service.reset_password(user_id, request.password)
    await operations.record_event(
        "user.password_reset",
        "Administrator reset a local user's password",
        actor=actor,
        target_type="user",
        target_id=str(user_id),
        component="users",
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    actor: Administrator,
    service: UserServiceDep,
    operations: OperationsDep,
) -> None:
    await service.delete_user(user_id, actor.id)
    await operations.record_event(
        "user.deleted",
        "Local user deleted",
        actor=actor,
        target_type="user",
        target_id=str(user_id),
        component="users",
    )
