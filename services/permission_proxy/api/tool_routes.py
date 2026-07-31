from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field

from services.common.database import Database
from services.common.settings import PermissionProxySettings
from services.permission_proxy.api.security_routes import (
    authentication_exception,
    authorization_exception,
    bearer_scheme,
    session_exception,
)
from services.permission_proxy.audit.service import AuditService
from services.permission_proxy.policy.evaluator import PolicyEvaluator
from services.permission_proxy.security.auth import (
    AccessTokenService,
    AuthenticationError,
    AuthorizationError,
    IdentityService,
    require_scopes,
)
from services.permission_proxy.security.sessions import (
    TrustedSessionError,
    TrustedSessionService,
)
from services.permission_proxy.tool_calls import ToolCallService
from services.permission_proxy.tools.crm import ToolAdapter


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=100)
    operation: str = Field(min_length=1, max_length=100)
    parameters: dict[str, Any]


class ToolCallResponse(BaseModel):
    request_id: str
    decision: str
    reason_code: str
    message: str
    result: dict[str, Any] | None = None


def build_tool_router(
    *,
    database: Database,
    settings: PermissionProxySettings,
    adapter: ToolAdapter,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["tool calls"])
    access_tokens = AccessTokenService(settings)
    identities = IdentityService(database)
    trusted_sessions = TrustedSessionService(database, settings)
    service = ToolCallService(
        evaluator=PolicyEvaluator(database),
        audit=AuditService(database),
        adapter=adapter,
    )

    @router.post("/tool-calls", response_model=ToolCallResponse)
    async def execute_tool_call(
        request: ToolCallRequest,
        response: Response,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(bearer_scheme),
        ],
        session_token: Annotated[str, Header(alias="X-Session-Token", min_length=1)],
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", min_length=8, max_length=128),
        ],
        trace_id: Annotated[
            str | None,
            Header(alias="Traceparent", max_length=256),
        ] = None,
    ) -> ToolCallResponse:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "MISSING_ACCESS_TOKEN", "message": "A Bearer token is required"},
            )
        try:
            principal = access_tokens.decode(credentials.credentials)
            require_scopes(principal, "tool:invoke")
            agent = identities.resolve_active_agent(principal)
            session = trusted_sessions.validate(
                session_token,
                expected_agent_id=agent.agent_id,
            )
        except AuthenticationError as error:
            raise authentication_exception(error) from error
        except AuthorizationError as error:
            raise authorization_exception(error) from error
        except TrustedSessionError as error:
            raise session_exception(error) from error

        outcome = await service.execute(
            agent_id=agent.agent_id,
            trusted_session=session,
            idempotency_key=idempotency_key,
            tool=request.tool,
            operation=request.operation,
            parameters=request.parameters,
            trace_id=trace_id,
        )
        if outcome.reason_code == "DUPLICATE_REQUEST":
            response.status_code = status.HTTP_409_CONFLICT
        elif outcome.decision == "block":
            response.status_code = status.HTTP_403_FORBIDDEN
        elif outcome.reason_code == "UPSTREAM_TOOL_TIMEOUT":
            response.status_code = status.HTTP_504_GATEWAY_TIMEOUT
        elif outcome.decision == "error":
            response.status_code = status.HTTP_502_BAD_GATEWAY

        return ToolCallResponse(
            request_id=outcome.request_id,
            decision=outcome.decision,
            reason_code=outcome.reason_code,
            message=outcome.message,
            result=outcome.result,
        )

    return router
