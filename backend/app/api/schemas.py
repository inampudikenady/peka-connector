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
    next_scheduled_scan_at: datetime | None
    last_scheduled_scan_at: datetime | None
    scan_in_progress: bool


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


class ManagedDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID
    document_key: str
    relative_path: str
    filename: str
    normalized_filename: str
    extension: str
    mime_type: str
    size_bytes: int
    content_hash: str
    modified_at: datetime
    discovered_at: datetime
    first_seen_at: datetime
    last_seen_at: datetime
    state: str
    local_status: str
    delivery_status: str
    upload_attempt_count: int
    last_upload_attempt_at: datetime | None
    uploaded_at: datetime | None
    remote_document_id: str | None
    remote_version_id: str | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    entry_method: str
    can_delete: bool
    delete_unavailable_reason: str | None
    deletion_in_progress: bool


class PaginatedManagedDocumentsResponse(BaseModel):
    items: list[ManagedDocumentResponse]
    total: int
    page: int
    page_size: int


class DocumentUploadResult(BaseModel):
    filename: str
    success: bool
    document: ManagedDocumentResponse | None = None
    code: str | None = None
    message: str


class DocumentUploadBatchResponse(BaseModel):
    results: list[DocumentUploadResult]


class ManagedDocumentSourceResponse(BaseModel):
    id: UUID
    name: str
    plugin_type: Literal["filesystem_documents"]
    path: Literal["/data/sources/documents"]
    enabled: bool
    system_managed: Literal[True]
    scan_interval_seconds: int
    last_scan_at: datetime | None
    next_scheduled_scan_at: datetime | None
    last_scan_result: str
    discovered_document_count: int
    health_status: str
    last_error: str | None


class ManagedDocumentSourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    scan_interval_seconds: int = Field(ge=30, le=86400)


class ManagedDocumentScanResponse(BaseModel):
    discovered: int
    changed: int
    unchanged: int
    removed: int
    delayed: int


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
    trigger: Literal["manual", "scheduled"]
    correlation_id: UUID


class PaginatedScansResponse(BaseModel):
    items: list[ScanResponse]
    total: int
    page: int
    page_size: int


class ScanDetailResponse(ScanResponse):
    source_name: str
    log_references: list[str]


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    actor_username: str | None
    target_type: str | None
    target_id: str | None
    message: str
    created_at: datetime
    outcome: Literal["success", "warning", "failure", "information"]


class PaginatedActivityResponse(BaseModel):
    items: list[ActivityResponse]
    total: int
    page: int
    page_size: int


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
    saas_status: str
    connector_id: str | None
    tenant_id: str | None
    saas_url: str | None
    last_heartbeat_at: datetime | None
    instance_id: str
    registered_at: datetime | None
    heartbeat_interval_seconds: int
    last_heartbeat_attempt_at: datetime | None
    next_heartbeat_at: datetime | None
    last_heartbeat_status: str | None
    last_heartbeat_error: str | None
    heartbeat_failure_count: int
    last_heartbeat_failed_at: datetime | None
    heartbeat_round_trip_ms: float | None
    last_saas_server_time: datetime | None
    metadata_sync_warning: str | None = None


class ProductSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_display_name: str = Field(min_length=1, max_length=200)
    environment_label: str = Field(min_length=1, max_length=100)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class OverviewResponse(BaseModel):
    connector_status: str
    saas_status: str
    last_heartbeat_at: datetime | None
    connector_version: str
    source_count: int
    enabled_source_count: int
    unhealthy_source_count: int
    recent_events: list[ActivityResponse]
    storage_total_bytes: int | None
    storage_free_bytes: int | None
    connector_display_name: str
    instance_id: str
    connector_id: str | None
    tenant_id: str | None
    next_heartbeat_at: datetime | None
    heartbeat_failure_count: int
    last_heartbeat_error: str | None
    saas_url: str | None
    registered_at: datetime | None
    last_heartbeat_attempt_at: datetime | None
    heartbeat_interval_seconds: int
    heartbeat_round_trip_ms: float | None
    scheduler_running: bool
    heartbeat_job_scheduled: bool
    source_scheduler_job_count: int
    document_total: int
    document_queued: int
    document_uploading: int
    document_uploaded: int
    document_failed: int
    document_unsupported: int
    last_document_delivery_at: datetime | None
    document_endpoint_status: str
    document_source_health: str
    document_source_last_scan_at: datetime | None
    document_source_next_scan_at: datetime | None


class SaaSConnectivityRequest(BaseModel):
    saas_url: str = Field(min_length=1, max_length=500)


class SaaSRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    saas_url: str = Field(min_length=1, max_length=500)
    registration_token: str = Field(min_length=20, max_length=512)
    confirmed: bool = False


class ConfirmationRequest(BaseModel):
    confirmed: bool


class ActionResponse(BaseModel):
    message: str


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
    instance_id: str
    registration_state: str
    connection_state: str
    saas_hostname: str | None
    last_heartbeat_attempt_at: datetime | None
    last_successful_heartbeat_at: datetime | None
    next_heartbeat_at: datetime | None
    heartbeat_interval_seconds: int
    consecutive_failures: int
    latest_heartbeat_failure_reason: str | None
    heartbeat_round_trip_ms: float | None
    scheduler_running: bool
    heartbeat_job_scheduled: bool
    source_scheduler_job_count: int
    document_worker_running: bool
    document_reconciliation_scheduled: bool
    pending_document_jobs: int
    stale_document_jobs: int


class HealthResponse(BaseModel):
    status: Literal["healthy"] = "healthy"
    version: str
