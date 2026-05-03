from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UploadServerApiVersionsIn(BaseModel):
    """Upload host base URLs (same shape as browser localStorage)."""

    prod: str = ""
    profile: str = ""
    debug: str = ""


class UploadServerApiVersionsOut(BaseModel):
    release: str | None = None
    profile: str | None = None
    debug: str | None = None


class ReleaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: str
    build_type: str
    server_version: str
    release_notes: str
    file_path: str
    platform: str
    artifact_kind: str
    web_url: str | None
    force_update: bool
    created_at: datetime


class LatestVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: str
    server_version: str
    build_type: str
    platform: str
    artifact_kind: str
    force_update: bool
    created_at: datetime
    web_url: str | None
    download_url: str


class GetLatestStatEventIn(BaseModel):
    kind: Literal["download", "share"]
    platform: str = Field(min_length=1, max_length=32)
    build_type: str = Field(min_length=1, max_length=32)


class GetLatestStatCountsOut(BaseModel):
    download_count: int
    share_count: int
