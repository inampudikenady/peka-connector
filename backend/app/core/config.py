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
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(default=30, ge=5, le=1440)
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: SecretStr | None = None
    cors_origins: list[str] = []
    refresh_token_days: int = Field(default=7, ge=1, le=30)
    cookie_secure: bool = False

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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
