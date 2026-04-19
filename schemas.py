from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    created_at: datetime
