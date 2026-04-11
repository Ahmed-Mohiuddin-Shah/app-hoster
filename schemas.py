from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
