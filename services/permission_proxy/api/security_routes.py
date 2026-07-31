from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.common.database import Database
from services.common.settings import PermissionProxySettings
from services.permission_proxy.api.schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    IdentityResponse,
    RevokeSessionResponse,
    ValidateSessionRequest,
    ValidateSessionResponse,
)
from services.permission_proxy.security.auth import (
    AccessTokenService,
    AuthenticationError,
    AuthorizationError,
    IdentityService,
    Principal,
    require_scopes,
)
from services.permission_proxy.security.sessions import (
    TrustedSessionError,
    TrustedSessionService,
)

bearer_scheme = HTTPBearer(auto_error=False)


def authentication_exception(error: AuthenticationError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": error.code, "message": error.message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def authorization_exception(error: AuthorizationError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": error.code, "message": error.message},
    )


def session_exception(error: TrustedSessionError) -> HTTPException:
    if error.code in {
        "INVALID_SESSION_TOKEN",
        "INVALID_SESSION_TOKEN_USE",
        "SESSION_TOKEN_EXPIRED",
        "SESSION_EXPIRED",
        "SESSION_NOT_ACTIVE",
        "SESSION_JTI_MISMATCH",
        "SESSION_CLAIMS_MISMATCH",
    }:
        response_status = status.HTTP_401_UNAUTHORIZED
    elif error.code in {"SESSION_AGENT_MISMATCH", "AGENT_NOT_ACTIVE"}:
        response_status = status.HTTP_403_FORBIDDEN
    elif error.code in {"AGENT_NOT_FOUND", "SESSION_NOT_FOUND"}:
        response_status = status.HTTP_404_NOT_FOUND
    else:
        response_status = status.HTTP_400_BAD_REQUEST
    return HTTPException(
        status_code=response_status,
        detail={"code": error.code, "message": error.message},
    )


def build_security_router(
    *,
    database: Database,
    settings: PermissionProxySettings,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["identity and sessions"])
    access_tokens = AccessTokenService(settings)
    identities = IdentityService(database)
    trusted_sessions = TrustedSessionService(database, settings)

    def authenticated_principal(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(bearer_scheme),
        ],
    ) -> Principal:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "MISSING_ACCESS_TOKEN",
                    "message": "A Bearer access token is required",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            return access_tokens.decode(credentials.credentials)
        except AuthenticationError as error:
            raise authentication_exception(error) from error

    PrincipalDependency = Annotated[Principal, Depends(authenticated_principal)]

    @router.get("/identity/me", response_model=IdentityResponse)
    def identity_me(principal: PrincipalDependency) -> IdentityResponse:
        agent_id: str | None = None
        agent_status: str | None = None
        if principal.token_use == "agent":
            try:
                agent = identities.resolve_active_agent(principal)
            except AuthorizationError as error:
                raise authorization_exception(error) from error
            agent_id = agent.agent_id
            agent_status = agent.status.value

        return IdentityResponse(
            subject=principal.subject,
            token_use=principal.token_use,
            scopes=sorted(principal.scopes),
            agent_id=agent_id,
            agent_status=agent_status,
        )

    @router.post(
        "/sessions",
        response_model=CreateSessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_session(
        request: CreateSessionRequest,
        principal: PrincipalDependency,
    ) -> CreateSessionResponse:
        try:
            if principal.token_use not in {"host", "admin"}:
                raise AuthorizationError(
                    "TRUSTED_HOST_TOKEN_REQUIRED",
                    "A trusted host or administrator token is required",
                )
            require_scopes(principal, "session:create")
            created = trusted_sessions.create(
                agent_id=request.agent_id,
                user_id=request.user_id,
                customer_id=request.customer_id,
                created_by_subject=principal.subject,
                ttl_seconds=request.ttl_seconds,
            )
        except AuthorizationError as error:
            raise authorization_exception(error) from error
        except TrustedSessionError as error:
            raise session_exception(error) from error

        return CreateSessionResponse(
            session_id=created.session_id,
            session_token=created.session_token,
            agent_id=created.agent_id,
            user_id=created.user_id,
            customer_id=created.customer_id,
            expires_at=created.expires_at,
        )

    @router.post("/sessions/validate", response_model=ValidateSessionResponse)
    def validate_session(
        request: ValidateSessionRequest,
        principal: PrincipalDependency,
    ) -> ValidateSessionResponse:
        try:
            require_scopes(principal, "tool:invoke")
            agent = identities.resolve_active_agent(principal)
            claims = trusted_sessions.validate(
                request.session_token,
                expected_agent_id=agent.agent_id,
            )
        except AuthorizationError as error:
            raise authorization_exception(error) from error
        except TrustedSessionError as error:
            raise session_exception(error) from error

        return ValidateSessionResponse(
            session_id=claims.session_id,
            agent_id=claims.agent_id,
            user_id=claims.user_id,
            customer_id=claims.customer_id,
            issued_at=claims.issued_at,
            expires_at=claims.expires_at,
        )

    @router.post(
        "/sessions/{session_id}/revoke",
        response_model=RevokeSessionResponse,
    )
    def revoke_session(
        session_id: str,
        principal: PrincipalDependency,
    ) -> RevokeSessionResponse:
        try:
            if principal.token_use not in {"host", "admin"}:
                raise AuthorizationError(
                    "TRUSTED_HOST_TOKEN_REQUIRED",
                    "A trusted host or administrator token is required",
                )
            require_scopes(principal, "session:revoke")
            revoked = trusted_sessions.revoke(session_id)
        except AuthorizationError as error:
            raise authorization_exception(error) from error
        except TrustedSessionError as error:
            raise session_exception(error) from error

        return RevokeSessionResponse(
            session_id=revoked.session_id,
            status=revoked.status.value,
            revoked_at=revoked.revoked_at,
        )

    return router
