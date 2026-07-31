from functools import lru_cache
from typing import Literal, Self

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class BaseServiceSettings(BaseSettings):
    """Settings shared by every independently deployable service."""

    app_env: Environment = "local"
    log_level: LogLevel = "INFO"
    service_version: str = "0.1.0"
    host: str = "0.0.0.0"
    port: int = Field(ge=1, le=65535)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


class PermissionProxySettings(BaseServiceSettings):
    """Validated configuration for the permission proxy."""

    service_name: str = "permission-proxy"
    port: int = 8000
    database_url: str = (
        "postgresql+psycopg://permission:permission@localhost:5432/permission_enforcer"
    )
    redis_url: str = "redis://localhost:6379/0"
    crm_base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8001")
    crm_internal_api_key: SecretStr = SecretStr("local-development-only-change-me")
    upstream_timeout_seconds: float = Field(default=5.0, ge=0.1, le=30)
    oidc_issuer: AnyHttpUrl = AnyHttpUrl("http://localhost:8081/dev-issuer")
    oidc_audience: str = "tool-permission-enforcer"
    oidc_jwks_url: AnyHttpUrl | None = None
    oidc_algorithm: Literal["RS256", "ES256"] = "RS256"
    dev_auth_enabled: bool = True
    dev_jwt_secret: SecretStr = SecretStr("local-development-access-token-secret-change-me")
    session_token_issuer: str = "tool-permission-enforcer"
    session_token_audience: str = "agent-session"
    session_signing_secret: SecretStr = SecretStr("local-development-session-secret-change-me")
    session_token_ttl_seconds: int = Field(default=1800, ge=60, le=3600)

    model_config = SettingsConfigDict(
        env_prefix="PROXY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator(
        "crm_internal_api_key",
        "dev_jwt_secret",
        "session_signing_secret",
    )
    @classmethod
    def require_strong_hmac_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT signing secrets must contain at least 32 characters")
        return value

    @model_validator(mode="after")
    def prohibit_development_auth_in_production(self) -> Self:
        if self.app_env == "production" and self.dev_auth_enabled:
            raise ValueError("PROXY_DEV_AUTH_ENABLED must be false in production")
        if self.app_env == "production" and self.oidc_issuer.scheme != "https":
            raise ValueError("PROXY_OIDC_ISSUER must use HTTPS in production")
        if self.app_env == "production" and self.oidc_jwks_url is None:
            raise ValueError("PROXY_OIDC_JWKS_URL is required in production")
        if (
            self.app_env == "production"
            and self.session_signing_secret.get_secret_value()
            == "local-development-session-secret-change-me"
        ):
            raise ValueError("PROXY_SESSION_SIGNING_SECRET must be changed in production")
        if (
            self.app_env == "production"
            and self.crm_internal_api_key.get_secret_value() == "local-development-only-change-me"
        ):
            raise ValueError("PROXY_CRM_INTERNAL_API_KEY must be changed in production")
        return self


class SampleCRMSettings(BaseServiceSettings):
    """Validated configuration for the private sample CRM."""

    service_name: str = "sample-crm"
    port: int = 8001
    database_url: str = (
        "postgresql+psycopg://permission:permission@localhost:5432/permission_enforcer"
    )
    internal_api_key: SecretStr = SecretStr("local-development-only-change-me")

    model_config = SettingsConfigDict(
        env_prefix="CRM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("internal_api_key")
    @classmethod
    def require_strong_internal_key(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("CRM internal API key must contain at least 32 characters")
        return value

    @model_validator(mode="after")
    def prohibit_default_key_in_production(self) -> Self:
        if (
            self.app_env == "production"
            and self.internal_api_key.get_secret_value() == "local-development-only-change-me"
        ):
            raise ValueError("CRM_INTERNAL_API_KEY must be changed in production")
        return self


class ReferenceAgentSettings(BaseServiceSettings):
    """Validated configuration for the reference LLM agent."""

    service_name: str = "reference-agent"
    port: int = 8002
    proxy_base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8000")
    llm_provider: str = "disabled"
    llm_api_key: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_prefix="AGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def require_key_when_provider_is_enabled(self) -> Self:
        if self.llm_provider != "disabled" and self.llm_api_key is None:
            raise ValueError("AGENT_LLM_API_KEY is required when AGENT_LLM_PROVIDER is enabled")
        return self


@lru_cache
def get_proxy_settings() -> PermissionProxySettings:
    return PermissionProxySettings()


@lru_cache
def get_crm_settings() -> SampleCRMSettings:
    return SampleCRMSettings()


@lru_cache
def get_agent_settings() -> ReferenceAgentSettings:
    return ReferenceAgentSettings()
