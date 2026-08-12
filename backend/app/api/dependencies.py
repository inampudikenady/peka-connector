from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.auth import AuthenticationService
from app.application.services.certificates import TrustedCertificateService
from app.application.services.cmdb import CMDBService
from app.application.services.documents import ManagedDocumentService
from app.application.services.integrations import IntegrationService
from app.application.services.inventory import InventoryService
from app.application.services.knowledge import LocalKnowledgeService
from app.application.services.loki import LokiService
from app.application.services.prometheus import PrometheusService
from app.application.services.saas import RegistrationService
from app.application.services.servicenow import ServiceNowService
from app.application.services.sources import SourceService
from app.application.services.users import UserService
from app.application.services.zammad import ZammadService
from app.core.config import Settings, get_settings
from app.domain.entities.source import UserAccount
from app.infrastructure.auth.tokens import decode_access_token
from app.infrastructure.database.repositories.documents import SqlAlchemyDocumentRepository
from app.infrastructure.database.repositories.operations import SqlAlchemyOperationsRepository
from app.infrastructure.database.repositories.scans import SqlAlchemyScanRepository
from app.infrastructure.database.repositories.sessions import SqlAlchemyRefreshTokenRepository
from app.infrastructure.database.repositories.sources import SqlAlchemySourceRepository
from app.infrastructure.database.repositories.users import SqlAlchemyUserRepository
from app.infrastructure.database.session import get_session
from app.infrastructure.saas.client import HttpxPEKASaaSClient
from app.infrastructure.scheduling import connector_scheduler
from app.infrastructure.security.secrets import SecretEncryptionService
from app.plugins.registry import plugin_registry

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
bearer = HTTPBearer(auto_error=False)


def get_auth_service(session: SessionDep, settings: SettingsDep) -> AuthenticationService:
    return AuthenticationService(
        SqlAlchemyUserRepository(session),
        SqlAlchemyRefreshTokenRepository(session),
        settings,
    )


def get_source_service(session: SessionDep) -> SourceService:
    return SourceService(
        SqlAlchemySourceRepository(session),
        SqlAlchemyDocumentRepository(session),
        SqlAlchemyScanRepository(session),
        plugin_registry,
    )


def get_user_service(session: SessionDep) -> UserService:
    return UserService(SqlAlchemyUserRepository(session), SqlAlchemyRefreshTokenRepository(session))


def get_operations_repository(session: SessionDep) -> SqlAlchemyOperationsRepository:
    return SqlAlchemyOperationsRepository(session)


def get_document_service(session: SessionDep, settings: SettingsDep) -> ManagedDocumentService:
    return ManagedDocumentService(session, settings)


def get_knowledge_service(session: SessionDep, settings: SettingsDep) -> LocalKnowledgeService:
    return LocalKnowledgeService(session, settings)


def get_cmdb_service(session: SessionDep, settings: SettingsDep) -> CMDBService:
    return CMDBService(session, settings)


def get_certificate_service(
    session: SessionDep, settings: SettingsDep
) -> TrustedCertificateService:
    return TrustedCertificateService(session, settings)


def get_inventory_service(session: SessionDep) -> InventoryService:
    return InventoryService(session)


def get_prometheus_service(session: SessionDep, settings: SettingsDep) -> PrometheusService:
    return PrometheusService(session, SecretEncryptionService(settings.encryption_key), settings)


def get_loki_service(session: SessionDep, settings: SettingsDep) -> LokiService:
    return LokiService(session, SecretEncryptionService(settings.encryption_key), settings)


def get_zammad_service(session: SessionDep, settings: SettingsDep) -> ZammadService:
    return ZammadService(session, SecretEncryptionService(settings.encryption_key))


def get_servicenow_service(session: SessionDep, settings: SettingsDep) -> ServiceNowService:
    return ServiceNowService(session, SecretEncryptionService(settings.encryption_key))


def get_integration_service(session: SessionDep, settings: SettingsDep) -> IntegrationService:
    return IntegrationService(session, SecretEncryptionService(settings.encryption_key))


def get_registration_service(session: SessionDep, settings: SettingsDep) -> RegistrationService:
    return RegistrationService(
        SqlAlchemyOperationsRepository(session),
        HttpxPEKASaaSClient(
            settings.saas_connect_timeout_seconds,
            settings.saas_read_timeout_seconds,
            settings.tls_verify,
        ),
        SecretEncryptionService(settings.encryption_key),
        settings,
        connector_scheduler,
    )


async def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> UserAccount:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = decode_access_token(credentials.credentials, settings)
        if payload.get("type") != "access":
            raise unauthorized
        user_id = UUID(str(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise unauthorized from exc
    user = await SqlAlchemyUserRepository(session).get_by_id(user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


CurrentUser = Annotated[UserAccount, Depends(get_current_user)]


async def require_administrator(user: CurrentUser) -> UserAccount:
    if user.role != "administrator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role required",
        )
    return user


Administrator = Annotated[UserAccount, Depends(require_administrator)]
AuthServiceDep = Annotated[AuthenticationService, Depends(get_auth_service)]
SourceServiceDep = Annotated[SourceService, Depends(get_source_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
OperationsDep = Annotated[SqlAlchemyOperationsRepository, Depends(get_operations_repository)]
DocumentServiceDep = Annotated[ManagedDocumentService, Depends(get_document_service)]
KnowledgeServiceDep = Annotated[LocalKnowledgeService, Depends(get_knowledge_service)]
CMDBServiceDep = Annotated[CMDBService, Depends(get_cmdb_service)]
CertificateServiceDep = Annotated[TrustedCertificateService, Depends(get_certificate_service)]
InventoryServiceDep = Annotated[InventoryService, Depends(get_inventory_service)]
PrometheusServiceDep = Annotated[PrometheusService, Depends(get_prometheus_service)]
LokiServiceDep = Annotated[LokiService, Depends(get_loki_service)]
ZammadServiceDep = Annotated[ZammadService, Depends(get_zammad_service)]
ServiceNowServiceDep = Annotated[ServiceNowService, Depends(get_servicenow_service)]
IntegrationServiceDep = Annotated[IntegrationService, Depends(get_integration_service)]
RegistrationServiceDep = Annotated[RegistrationService, Depends(get_registration_service)]
