from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from services.common.settings import PermissionProxySettings
from services.permission_proxy.security.auth import (
    AccessTokenService,
    AuthenticationError,
    AuthorizationError,
    Principal,
    require_scopes,
)


def development_settings(**overrides: Any) -> PermissionProxySettings:
    values: dict[str, Any] = {
        "_env_file": None,
        "app_env": "test",
        "database_url": "sqlite+pysqlite:///:memory:",
        "crm_internal_api_key": "test-proxy-to-crm-key-that-is-long-enough",
    }
    values.update(overrides)
    return PermissionProxySettings(**values)


def test_development_access_token_round_trip() -> None:
    service = AccessTokenService(development_settings())

    token = service.issue_development_token(
        subject="dev:agent_support_001",
        token_use="agent",
        scopes={"tool:invoke", "identity:read"},
    )
    principal = service.decode(token)

    assert principal.subject == "dev:agent_support_001"
    assert principal.token_use == "agent"
    assert principal.scopes == frozenset({"tool:invoke", "identity:read"})


def test_access_token_rejects_expired_and_wrong_signature_tokens() -> None:
    settings = development_settings()
    service = AccessTokenService(settings)
    expired = service.issue_development_token(
        subject="dev:trusted-host",
        token_use="host",
        scopes={"session:create"},
        ttl_seconds=-1,
    )

    with pytest.raises(AuthenticationError, match="expired") as expired_error:
        service.decode(expired)
    assert expired_error.value.code == "ACCESS_TOKEN_EXPIRED"

    wrong_signature = jwt.encode(
        {
            "iss": str(settings.oidc_issuer),
            "aud": settings.oidc_audience,
            "sub": "dev:trusted-host",
            "token_use": "host",
            "scope": "session:create",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        "a-different-secret-that-is-long-enough-for-tests",
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError) as signature_error:
        service.decode(wrong_signature)
    assert signature_error.value.code == "INVALID_ACCESS_TOKEN"


def test_scope_enforcement_lists_missing_scopes() -> None:
    principal = Principal(
        subject="dev:trusted-host",
        token_use="host",
        scopes=frozenset({"session:create"}),
        claims={},
    )

    require_scopes(principal, "session:create")
    with pytest.raises(AuthorizationError, match="session:revoke") as error:
        require_scopes(principal, "session:create", "session:revoke")
    assert error.value.code == "INSUFFICIENT_SCOPE"


@dataclass
class FakeSigningKey:
    key: Any


class FakeSigningKeyProvider:
    def __init__(self, public_key: Any) -> None:
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token: str) -> FakeSigningKey:
        assert token
        return FakeSigningKey(key=self.public_key)


def test_production_oidc_token_uses_configured_signing_key_provider() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = development_settings(
        app_env="production",
        dev_auth_enabled=False,
        oidc_issuer="https://identity.example.com",
        oidc_jwks_url="https://identity.example.com/.well-known/jwks.json",
        session_signing_secret="production-session-secret-with-at-least-32-characters",
    )
    service = AccessTokenService(
        settings,
        signing_key_provider=FakeSigningKeyProvider(private_key.public_key()),
    )
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": str(settings.oidc_issuer),
            "aud": settings.oidc_audience,
            "sub": "prod:agent:001",
            "token_use": "agent",
            "scp": ["tool:invoke"],
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    principal = service.decode(token)

    assert principal.subject == "prod:agent:001"
    assert principal.scopes == frozenset({"tool:invoke"})
