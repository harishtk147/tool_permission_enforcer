from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict

from services.common.database import Database
from services.common.settings import PermissionProxySettings
from services.permission_proxy.api.security_routes import (
    authentication_exception,
    authorization_exception,
    bearer_scheme,
)
from services.permission_proxy.audit.service import AuditService
from services.permission_proxy.persistence.repositories import AuditEventRepository
from services.permission_proxy.security.auth import (
    AccessTokenService,
    AuthenticationError,
    AuthorizationError,
    Principal,
    require_scopes,
)


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    request_id: str
    idempotency_key: str
    sequence: int
    timestamp: datetime
    agent_id: str
    session_id: str | None
    user_id: str | None
    tool: str
    operation: str
    sanitized_parameters: dict[str, object]
    decision: str
    reason_code: str
    matched_manifest_id: str | None
    policy_checksum: str | None
    execution_status: str
    upstream_status_code: int | None
    decision_latency_ms: int | None
    total_latency_ms: int | None
    trace_id: str | None
    previous_record_hash: str | None
    record_hash: str


class AuditEventListResponse(BaseModel):
    events: list[AuditEventResponse]
    limit: int
    offset: int


class AuditIntegrityResponse(BaseModel):
    valid: bool
    events_checked: int
    first_invalid_event_id: str | None


def build_audit_router(
    *,
    database: Database,
    settings: PermissionProxySettings,
) -> APIRouter:
    router = APIRouter(prefix="/v1/audit", tags=["audit"])
    tokens = AccessTokenService(settings)
    audit = AuditService(database)

    def audit_principal(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(bearer_scheme),
        ],
    ) -> Principal:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "MISSING_ACCESS_TOKEN", "message": "A Bearer token is required"},
            )
        try:
            principal = tokens.decode(credentials.credentials)
            if principal.token_use not in {"auditor", "admin"}:
                raise AuthorizationError(
                    "AUDITOR_TOKEN_REQUIRED",
                    "An auditor or administrator token is required",
                )
            require_scopes(principal, "audit:read")
            return principal
        except AuthenticationError as error:
            raise authentication_exception(error) from error
        except AuthorizationError as error:
            raise authorization_exception(error) from error

    AuditPrincipal = Annotated[Principal, Depends(audit_principal)]

    @router.get("/events", response_model=AuditEventListResponse)
    def list_events(
        _: AuditPrincipal,
        agent_id: str | None = None,
        session_id: str | None = None,
        tool: str | None = None,
        operation: str | None = None,
        decision: str | None = None,
        reason_code: str | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> AuditEventListResponse:
        with database.session() as session:
            events = AuditEventRepository(session).list_events(
                agent_id=agent_id,
                session_id=session_id,
                tool=tool,
                operation=operation,
                decision=decision,
                reason_code=reason_code,
                limit=limit,
                offset=offset,
            )
            return AuditEventListResponse(
                events=[AuditEventResponse.model_validate(event) for event in events],
                limit=limit,
                offset=offset,
            )

    @router.get("/events/{request_id}", response_model=list[AuditEventResponse])
    def events_for_request(
        request_id: str,
        _: AuditPrincipal,
    ) -> list[AuditEventResponse]:
        with database.session() as session:
            events = AuditEventRepository(session).list_by_request(request_id)
            if not events:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "AUDIT_REQUEST_NOT_FOUND"},
                )
            return [AuditEventResponse.model_validate(event) for event in events]

    @router.get("/integrity", response_model=AuditIntegrityResponse)
    def verify_integrity(_: AuditPrincipal) -> AuditIntegrityResponse:
        result = audit.verify_integrity()
        return AuditIntegrityResponse(
            valid=result.valid,
            events_checked=result.events_checked,
            first_invalid_event_id=result.first_invalid_event_id,
        )

    return router
