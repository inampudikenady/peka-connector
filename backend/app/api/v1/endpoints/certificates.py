from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from pydantic import BaseModel

from app.api.dependencies import Administrator, CertificateServiceDep, CurrentUser

router = APIRouter()


class CertificateStateRequest(BaseModel):
    enabled: bool


@router.get("")
async def list_certificates(
    _: CurrentUser, service: CertificateServiceDep
) -> list[dict[str, object]]:
    return await service.list()


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_certificate(
    _: Administrator,
    service: CertificateServiceDep,
    name: Annotated[str, Form(min_length=1, max_length=200)],
    file: Annotated[UploadFile, File()],
) -> dict[str, object]:
    return await service.upload(name, file.filename or "certificate.pem", await file.read())


@router.put("/{certificate_id}")
async def set_certificate_state(
    certificate_id: UUID,
    request: CertificateStateRequest,
    _: Administrator,
    service: CertificateServiceDep,
) -> dict[str, object]:
    return await service.set_enabled(certificate_id, request.enabled)


@router.delete("/{certificate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_certificate(
    certificate_id: UUID,
    _: Administrator,
    service: CertificateServiceDep,
) -> Response:
    await service.delete(certificate_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
