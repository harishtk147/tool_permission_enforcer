from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

import jwt
from jwt import InvalidTokenError, PyJWKClient

from services.common.database import Database
from services.common.settings import PermissionProxySettings
from services.permission_proxy.domain.enums import AgentStatus
from services.permission_proxy.domain.models import Agent
from services.permission_proxy.persistence.repositories import AgentRepository


class AuthenticationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AuthorizationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Principal:
    subject: str
    token_use: str
    scopes: frozenset[str]
    claims: dict[str, Any]


class SigningKey(Protocol):
    key: Any


class SigningKeyProvider(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> SigningKey: ...


def parse_scopes(claims: dict[str, Any]) -> frozenset[str]:
    raw_scope = claims.get("scope")
    raw_scp = claims.get("scp")
    scopes: set[str] = set()
    if isinstance(raw_scope, str):
        scopes.update(item for item in raw_scope.split() if item)
    if isinstance(raw_scp, list):
        scopes.update(item for item in raw_scp if isinstance(item, str) and item)
    return frozenset(scopes)


class AccessTokenService:
    """Validates production OIDC tokens or locally signed development tokens."""

    def __init__(
        self,
        settings: PermissionProxySettings,
        signing_key_provider: SigningKeyProvider | None = None,
    ) -> None:
        self.settings = settings
        self.signing_key_provider: SigningKeyProvider | None
        if signing_key_provider is not None:
            self.signing_key_provider = signing_key_provider
        elif not settings.dev_auth_enabled and settings.oidc_jwks_url is not None:
            self.signing_key_provider = cast(
                SigningKeyProvider,
                PyJWKClient(str(settings.oidc_jwks_url)),
            )
        else:
            self.signing_key_provider = None

    def decode(self, token: str) -> Principal:
        try:
            if self.settings.dev_auth_enabled:
                claims = jwt.decode(
                    token,
                    self.settings.dev_jwt_secret.get_secret_value(),
                    algorithms=["HS256"],
                    audience=self.settings.oidc_audience,
                    issuer=str(self.settings.oidc_issuer),
                    options={"require": ["exp", "iat", "iss", "aud", "sub", "token_use"]},
                )
            else:
                if self.signing_key_provider is None:
                    raise AuthenticationError(
                        "OIDC_CONFIGURATION_ERROR",
                        "The production signing-key provider is unavailable",
                    )
                signing_key = self.signing_key_provider.get_signing_key_from_jwt(token)
                claims = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=[self.settings.oidc_algorithm],
                    audience=self.settings.oidc_audience,
                    issuer=str(self.settings.oidc_issuer),
                    options={"require": ["exp", "iat", "iss", "aud", "sub", "token_use"]},
                )
        except AuthenticationError:
            raise
        except jwt.ExpiredSignatureError as error:
            raise AuthenticationError("ACCESS_TOKEN_EXPIRED", "Access token has expired") from error
        except InvalidTokenError as error:
            raise AuthenticationError("INVALID_ACCESS_TOKEN", "Access token is invalid") from error

        subject = claims.get("sub")
        token_use = claims.get("token_use")
        if not isinstance(subject, str) or not subject:
            raise AuthenticationError("INVALID_ACCESS_TOKEN", "Access token subject is invalid")
        if token_use not in {"agent", "host", "admin", "auditor"}:
            raise AuthenticationError("INVALID_TOKEN_USE", "Access token use is not supported")

        return Principal(
            subject=subject,
            token_use=token_use,
            scopes=parse_scopes(claims),
            claims=claims,
        )

    def issue_development_token(
        self,
        *,
        subject: str,
        token_use: str,
        scopes: set[str],
        ttl_seconds: int = 900,
    ) -> str:
        if not self.settings.dev_auth_enabled:
            raise AuthorizationError(
                "DEV_AUTH_DISABLED",
                "Development token issuance is disabled",
            )
        if token_use not in {"agent", "host", "admin", "auditor"}:
            raise ValueError("Unsupported development token type")
        now = datetime.now(UTC)
        claims = {
            "iss": str(self.settings.oidc_issuer),
            "aud": self.settings.oidc_audience,
            "sub": subject,
            "token_use": token_use,
            "scope": " ".join(sorted(scopes)),
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(seconds=ttl_seconds),
        }
        return jwt.encode(
            claims,
            self.settings.dev_jwt_secret.get_secret_value(),
            algorithm="HS256",
        )


def require_scopes(principal: Principal, *required_scopes: str) -> None:
    missing = set(required_scopes) - principal.scopes
    if missing:
        raise AuthorizationError(
            "INSUFFICIENT_SCOPE",
            f"Required scope is missing: {', '.join(sorted(missing))}",
        )


class IdentityService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def resolve_active_agent(self, principal: Principal) -> Agent:
        if principal.token_use != "agent":
            raise AuthorizationError(
                "AGENT_TOKEN_REQUIRED",
                "An agent access token is required",
            )

        with self.database.session() as session:
            agent = AgentRepository(session).get_by_oidc_subject(principal.subject)
            if agent is None:
                raise AuthorizationError(
                    "AGENT_IDENTITY_NOT_REGISTERED",
                    "The agent identity is not registered",
                )
            if agent.status != AgentStatus.ACTIVE:
                raise AuthorizationError(
                    "AGENT_NOT_ACTIVE",
                    "The agent identity is not active",
                )
            return agent
