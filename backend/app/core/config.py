from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from PEKA_* environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PEKA_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str = "production"
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./data/state/peka.db"
    static_assets_dir: Path = Path("./static")
    data_root: Path = Path("./data")
    sources_root: Path = Path("./sources")
    external_sources_root: Path | None = None
    jwt_secret: SecretStr = Field(min_length=32)
    encryption_key: SecretStr | None = Field(default=None, min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(default=30, ge=5, le=1440)
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: SecretStr | None = None
    cors_origins: list[str] = []
    refresh_token_days: int = Field(default=7, ge=1, le=30)
    cookie_secure: bool = False
    saas_connect_timeout_seconds: float = Field(default=5.0, ge=1, le=30)
    saas_read_timeout_seconds: float = Field(default=15.0, ge=1, le=120)
    tls_verify: bool = True
    document_max_file_size_bytes: int = Field(default=100 * 1024 * 1024, ge=1)
    document_max_files_per_request: int = Field(default=20, ge=1, le=100)
    document_max_request_size_bytes: int = Field(default=500 * 1024 * 1024, ge=1)
    document_max_filename_length: int = Field(default=255, ge=32, le=512)
    document_stability_seconds: int = Field(default=5, ge=1, le=300)
    document_reconcile_interval_seconds: int = Field(default=300, ge=10, le=86400)
    document_worker_interval_seconds: int = Field(default=5, ge=1, le=300)
    operational_tool_poll_interval_seconds: int = Field(default=2, ge=1, le=30)
    document_job_max_attempts: int = Field(default=8, ge=1, le=100)
    cmdb_max_file_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    cmdb_max_row_count: int = Field(default=100_000, ge=1, le=1_000_000)
    minimum_free_disk_bytes: int = Field(default=256 * 1024 * 1024, ge=1)

    @field_validator("database_url")
    @classmethod
    def require_sqlite(cls, value: str) -> str:
        if not value.startswith("sqlite+aiosqlite:///"):
            raise ValueError("PEKA Connector currently supports SQLite only")
        return value

    @field_validator("bootstrap_admin_username", mode="before")
    @classmethod
    def empty_username_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("bootstrap_admin_password", mode="before")
    @classmethod
    def empty_password_is_none(cls, value: object) -> object:
        return None if value == "" else value

    def ensure_database_directory(self) -> None:
        database_path = self.database_url.removeprefix("sqlite+aiosqlite:///")
        if database_path != ":memory:":
            Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    def ensure_data_directories(self) -> None:
        for name in ("state", "config", "logs", "spool"):
            directory = self.data_root / name
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)

    @property
    def managed_documents_root(self) -> Path:
        return self.sources_root / "documents"

    @property
    def filesystem_sources_root(self) -> Path:
        return self.external_sources_root or self.sources_root

    def ensure_managed_document_directory(self) -> None:
        self.managed_documents_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.managed_documents_root.chmod(0o700)

    @property
    def managed_cmdb_root(self) -> Path:
        return self.data_root / "sources" / "cmdb"

    def ensure_managed_cmdb_directory(self) -> None:
        self.managed_cmdb_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.managed_cmdb_root.chmod(0o700)

    @property
    def trusted_ca_root(self) -> Path:
        return self.data_root / "config" / "certificates"

    def ensure_trusted_ca_directory(self) -> None:
        self.trusted_ca_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.trusted_ca_root.chmod(0o700)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # Values are supplied by PEKA_* at runtime.
