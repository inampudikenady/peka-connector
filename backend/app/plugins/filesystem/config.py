from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class FilesystemSourceConfig(BaseModel):
    path: Path
    include_patterns: list[str] = Field(
        default_factory=lambda: ["**/*.pdf", "**/*.docx", "**/*.txt", "**/*.md"]
    )
    exclude_patterns: list[str] = Field(
        default_factory=lambda: ["**/~$*", "**/.*", "**/tmp/**", "**/archive/**"]
    )
    scan_interval_seconds: int = Field(default=300, ge=30, le=86400)

    @field_validator("path")
    @classmethod
    def path_must_be_absolute(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("path must be absolute")
        return value

    @field_validator("include_patterns")
    @classmethod
    def require_patterns(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one include pattern is required")
        return value
