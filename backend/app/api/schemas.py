from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class PluginResponse(BaseModel):
    plugin_type: str
    display_name: str
    configuration_schema: dict[str, Any]


class SourceWrite(BaseModel):
    plugin_type: str = Field(min_length=1, max_length=100)
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


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    relative_path: str
    filename: str
    extension: str
    size_bytes: int
    modified_at: datetime
    sha256: str


class ScanResponse(BaseModel):
    discovered_count: int


class HealthResponse(BaseModel):
    status: Literal["healthy"] = "healthy"
    version: str
