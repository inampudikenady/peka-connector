from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.validation import validate_password, validate_username

Role = Literal["administrator", "read_only"]


class SetupStatusResponse(BaseModel):
    setup_required: bool


class BootstrapRequest(BaseModel):
    username: str
    password: str
    confirm_password: str

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        return validate_username(value)

    @model_validator(mode="after")
    def valid_passwords(self) -> "BootstrapRequest":
        validate_password(self.password, self.username)
        if self.password != self.confirm_password:
            raise ValueError("Password confirmation does not match")
        return self


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    expires_in: int
    token_type: Literal["bearer"] = "bearer"


class CurrentUserResponse(BaseModel):
    id: UUID
    username: str
    role: Role


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)
    confirm_password: str = Field(min_length=12, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self) -> "ChangePasswordRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("Password confirmation does not match")
        return self


class UserCreateRequest(BaseModel):
    username: str
    password: str
    confirm_password: str
    role: Role

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        return validate_username(value)

    @model_validator(mode="after")
    def valid_passwords(self) -> "UserCreateRequest":
        validate_password(self.password, self.username)
        if self.password != self.confirm_password:
            raise ValueError("Password confirmation does not match")
        return self


class UserResetPasswordRequest(BaseModel):
    password: str
    confirm_password: str

    @model_validator(mode="after")
    def passwords_match(self) -> "UserResetPasswordRequest":
        if self.password != self.confirm_password:
            raise ValueError("Password confirmation does not match")
        return self


class UserStateRequest(BaseModel):
    enabled: bool


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    role: Role
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None


class PluginResponse(BaseModel):
    plugin_type: str
    display_name: str
    configuration_schema: dict[str, Any]


class SourceWrite(BaseModel):
    plugin_type: Literal["filesystem_documents"]
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    configuration: dict[str, Any]


class SourceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    enabled: bool
    configuration: dict[str, Any]


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plugin_type: str
    name: str
    enabled: bool
    configuration: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    health_status: str
    last_success_at: datetime | None
    last_error: str | None
    last_scan_at: datetime | None
    file_count: int


class SourceValidationResponse(BaseModel):
    valid: bool
    message: str


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    relative_path: str
    filename: str
    extension: str
    size_bytes: int
    modified_at: datetime
    sha256: str
    discovered_at: datetime | None
    last_seen_at: datetime | None
    state: str


class ScanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID
    status: str
    started_at: datetime
    completed_at: datetime | None
    discovered_count: int
    added_count: int
    changed_count: int
    unchanged_count: int
    missing_count: int
    failed_count: int
    error: str | None


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    actor_username: str | None
    target_type: str | None
    target_id: str | None
    message: str
    details: dict[str, Any]
    created_at: datetime


class LogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    level: str
    component: str
    message: str
    context: dict[str, Any]
    created_at: datetime


class PaginatedLogsResponse(BaseModel):
    items: list[LogResponse]
    total: int
    page: int
    page_size: int


class ProductSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    connector_display_name: str
    environment_label: str
    log_level: str
    timezone: str
    saas_status: str
    connector_id: str | None
    tenant_id: str | None
    saas_url: str | None
    last_heartbeat_at: datetime | None


class ProductSettingsUpdate(BaseModel):
    connector_display_name: str = Field(min_length=1, max_length=200)
    environment_label: str = Field(min_length=1, max_length=100)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    timezone: str = Field(min_length=1, max_length=100)
    saas_url: str | None = Field(default=None, max_length=500)


class OverviewResponse(BaseModel):
    connector_status: str
    saas_status: str
    last_heartbeat_at: datetime | None
    connector_version: str
    source_count: int
    enabled_source_count: int
    unhealthy_source_count: int
    recent_failures: list[ActivityResponse]
    storage_total_bytes: int | None
    storage_free_bytes: int | None


class DiagnosticCheck(BaseModel):
    name: str
    status: Literal["healthy", "warning", "unhealthy", "unavailable"]
    detail: str


class DiagnosticsResponse(BaseModel):
    version: str
    build: str
    python_version: str
    platform: str
    migration_revision: str | None
    checks: list[DiagnosticCheck]


class HealthResponse(BaseModel):
    status: Literal["healthy"] = "healthy"
    version: str
