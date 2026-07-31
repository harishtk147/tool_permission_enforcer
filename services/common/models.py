from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ServiceInfo(BaseModel):
    name: str
    version: str
    environment: str
    docs_url: str


class HealthResponse(BaseModel):
    service: str
    status: str
    version: str
    environment: str
    checks: dict[str, str] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
