from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from jwt import InvalidTokenError

from services.common.database import Database
from services.common.settings import PermissionProxySettings
from services.permission_proxy.domain.enums import AgentStatus, SessionStatus
from services.permission_proxy.domain.models import AgentSession
from services.permission_proxy.persistence.repositories import (
    AgentRepository,
    SessionRepository,
)


class TrustedSessionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TrustedSessionClaims:
    session_id: str
    token_jti: str
    agent_id: str
    user_id: str
    customer_id: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class CreatedTrustedSession:
    session_id: str
    session_token: str
    agent_id: str
    user_id: str
    customer_id: str
    expires_at: datetime


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SessionTokenCodec:
    def __init__(self, settings: PermissionProxySettings) -> None:
        self.settings = settings

    def issue(self, agent_session: AgentSession) -> str:
        claims = {
            "iss": self.settings.session_token_issuer,
            "aud": self.settings.session_token_audience,
            "sub": agent_session.session_id,
            "jti": agent_session.token_jti,
            "token_use": "agent_session",
            "agent_id": agent_session.agent_id,
            "user_id": agent_session.user_id,
            "customer_id": agent_session.customer_id,
            "iat": as_utc(agent_session.created_at),
            "nbf": as_utc(agent_session.created_at),
            "exp": as_utc(agent_session.expires_at),
        }
        return jwt.encode(
            claims,
            self.settings.session_signing_secret.get_secret_value(),
            algorithm="HS256",
        )

    def decode(self, token: str) -> TrustedSessionClaims:
        try:
            claims = jwt.decode(
                token,
                self.settings.session_signing_secret.get_secret_value(),
                algorithms=["HS256"],
                audience=self.settings.session_token_audience,
                issuer=self.settings.session_token_issuer,
                options={
                    "require": [
                        "exp",
                        "iat",
                        "iss",
                        "aud",
                        "sub",
                        "jti",
                        "token_use",
                        "agent_id",
                        "user_id",
                        "customer_id",
                    ]
                },
            )
        except jwt.ExpiredSignatureError as error:
            raise TrustedSessionError(
                "SESSION_TOKEN_EXPIRED",
                "Session token has expired",
            ) from error
        except InvalidTokenError as error:
            raise TrustedSessionError(
                "INVALID_SESSION_TOKEN",
                "Session token is invalid",
            ) from error

        if claims.get("token_use") != "agent_session":
            raise TrustedSessionError(
                "INVALID_SESSION_TOKEN_USE",
                "Token is not an agent session token",
            )

        required_strings: dict[str, str] = {}
        for key in ("sub", "jti", "agent_id", "user_id", "customer_id"):
            value = claims.get(key)
            if not isinstance(value, str) or not value:
                raise TrustedSessionError(
                    "INVALID_SESSION_TOKEN",
                    "Session token claims are invalid",
                )
            required_strings[key] = value

        return TrustedSessionClaims(
            session_id=required_strings["sub"],
            token_jti=required_strings["jti"],
            agent_id=required_strings["agent_id"],
            user_id=required_strings["user_id"],
            customer_id=required_strings["customer_id"],
            issued_at=datetime.fromtimestamp(claims["iat"], tz=UTC),
            expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
        )


class TrustedSessionService:
    def __init__(self, database: Database, settings: PermissionProxySettings) -> None:
        self.database = database
        self.settings = settings
        self.codec = SessionTokenCodec(settings)

    def create(
        self,
        *,
        agent_id: str,
        user_id: str,
        customer_id: str,
        created_by_subject: str,
        ttl_seconds: int | None = None,
    ) -> CreatedTrustedSession:
        requested_ttl = (
            self.settings.session_token_ttl_seconds if ttl_seconds is None else ttl_seconds
        )
        if requested_ttl < 60 or requested_ttl > self.settings.session_token_ttl_seconds:
            raise TrustedSessionError(
                "INVALID_SESSION_TTL",
                "Session TTL is outside the permitted range",
            )

        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=requested_ttl)
        with self.database.session() as database_session:
            agent = AgentRepository(database_session).get(agent_id, for_update=True)
            if agent is None:
                raise TrustedSessionError("AGENT_NOT_FOUND", "Agent does not exist")
            if agent.status != AgentStatus.ACTIVE:
                raise TrustedSessionError("AGENT_NOT_ACTIVE", "Agent is not active")

            agent_session = SessionRepository(database_session).add(
                AgentSession(
                    session_id=f"sess_{uuid4().hex}",
                    token_jti=uuid4().hex,
                    agent_id=agent_id,
                    user_id=user_id,
                    customer_id=customer_id,
                    created_by_subject=created_by_subject,
                    status=SessionStatus.ACTIVE,
                    created_at=now,
                    expires_at=expires_at,
                    revoked_at=None,
                )
            )
            session_token = self.codec.issue(agent_session)

        return CreatedTrustedSession(
            session_id=agent_session.session_id,
            session_token=session_token,
            agent_id=agent_session.agent_id,
            user_id=agent_session.user_id,
            customer_id=agent_session.customer_id,
            expires_at=as_utc(agent_session.expires_at),
        )

    def validate(
        self,
        token: str,
        *,
        expected_agent_id: str,
    ) -> TrustedSessionClaims:
        claims = self.codec.decode(token)
        if claims.agent_id != expected_agent_id:
            raise TrustedSessionError(
                "SESSION_AGENT_MISMATCH",
                "Session is not bound to the authenticated agent",
            )

        with self.database.session() as database_session:
            persisted = SessionRepository(database_session).get(claims.session_id)
            if persisted is None:
                raise TrustedSessionError("SESSION_NOT_FOUND", "Session does not exist")
            if persisted.token_jti != claims.token_jti:
                raise TrustedSessionError("SESSION_JTI_MISMATCH", "Session token was replaced")
            if persisted.status != SessionStatus.ACTIVE:
                raise TrustedSessionError(
                    "SESSION_NOT_ACTIVE",
                    "Session is not active",
                )
            if as_utc(persisted.expires_at) <= datetime.now(UTC):
                raise TrustedSessionError("SESSION_EXPIRED", "Session has expired")
            if (
                persisted.agent_id != claims.agent_id
                or persisted.user_id != claims.user_id
                or persisted.customer_id != claims.customer_id
            ):
                raise TrustedSessionError(
                    "SESSION_CLAIMS_MISMATCH",
                    "Session token does not match server-side state",
                )

            agent = AgentRepository(database_session).get(persisted.agent_id)
            if agent is None or agent.status != AgentStatus.ACTIVE:
                raise TrustedSessionError("AGENT_NOT_ACTIVE", "Agent is not active")

        return claims

    def revoke(self, session_id: str) -> AgentSession:
        with self.database.session() as database_session:
            persisted = SessionRepository(database_session).get(session_id)
            if persisted is None:
                raise TrustedSessionError("SESSION_NOT_FOUND", "Session does not exist")
            if persisted.status != SessionStatus.REVOKED:
                persisted.status = SessionStatus.REVOKED
                persisted.revoked_at = datetime.now(UTC)
                database_session.flush()
            return persisted
