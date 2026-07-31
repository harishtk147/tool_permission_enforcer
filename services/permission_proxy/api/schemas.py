from datetime import datetime

from pydantic import BaseModel, Field


class IdentityResponse(BaseModel):
    subject: str
    token_use: str
    scopes: list[str]
    agent_id: str | None = None
    agent_status: str | None = None


class CreateSessionRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=128)
    customer_id: str = Field(min_length=1, max_length=64)
    ttl_seconds: int | None = Field(default=None, ge=60, le=3600)


class CreateSessionResponse(BaseModel):
    session_id: str
    session_token: str
    agent_id: str
    user_id: str
    customer_id: str
    expires_at: datetime


class ValidateSessionRequest(BaseModel):
    session_token: str = Field(min_length=32, max_length=8192)


class ValidateSessionResponse(BaseModel):
    valid: bool = True
    session_id: str
    agent_id: str
    user_id: str
    customer_id: str
    issued_at: datetime
    expires_at: datetime


class RevokeSessionResponse(BaseModel):
    session_id: str
    status: str
    revoked_at: datetime | None


class ErrorDetail(BaseModel):
    code: str
    message: str
