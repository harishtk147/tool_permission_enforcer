import pytest
from pydantic import ValidationError

from services.common.settings import (
    PermissionProxySettings,
    ReferenceAgentSettings,
    SampleCRMSettings,
)


def test_proxy_defaults_are_safe_for_local_development() -> None:
    settings = PermissionProxySettings(_env_file=None, app_env="test")

    assert settings.service_name == "permission-proxy"
    assert settings.port == 8000
    assert settings.dev_auth_enabled is True


def test_proxy_reads_prefixed_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROXY_APP_ENV", "staging")
    monkeypatch.setenv("PROXY_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("PROXY_PORT", "9100")

    settings = PermissionProxySettings(_env_file=None)

    assert settings.app_env == "staging"
    assert settings.log_level == "WARNING"
    assert settings.port == 9100


def test_proxy_rejects_development_auth_in_production() -> None:
    with pytest.raises(ValidationError, match="DEV_AUTH_ENABLED"):
        PermissionProxySettings(
            _env_file=None,
            app_env="production",
            dev_auth_enabled=True,
            oidc_issuer="https://identity.example.com",
        )


def test_proxy_requires_https_oidc_in_production() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        PermissionProxySettings(
            _env_file=None,
            app_env="production",
            dev_auth_enabled=False,
            oidc_issuer="http://identity.example.com",
        )


def test_proxy_requires_jwks_in_production() -> None:
    with pytest.raises(ValidationError, match="OIDC_JWKS_URL"):
        PermissionProxySettings(
            _env_file=None,
            app_env="production",
            dev_auth_enabled=False,
            oidc_issuer="https://identity.example.com",
            session_signing_secret="production-session-signing-secret-value",
        )


def test_proxy_rejects_default_session_secret_in_production() -> None:
    with pytest.raises(ValidationError, match="SESSION_SIGNING_SECRET"):
        PermissionProxySettings(
            _env_file=None,
            app_env="production",
            dev_auth_enabled=False,
            oidc_issuer="https://identity.example.com",
            oidc_jwks_url="https://identity.example.com/.well-known/jwks.json",
        )


def test_proxy_rejects_default_crm_key_in_production() -> None:
    with pytest.raises(ValidationError, match="CRM_INTERNAL_API_KEY"):
        PermissionProxySettings(
            _env_file=None,
            app_env="production",
            dev_auth_enabled=False,
            oidc_issuer="https://identity.example.com",
            oidc_jwks_url="https://identity.example.com/.well-known/jwks.json",
            session_signing_secret="production-session-signing-secret-value",
        )


def test_proxy_rejects_short_signing_secrets() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        PermissionProxySettings(
            _env_file=None,
            app_env="test",
            session_signing_secret="too-short",
        )


def test_crm_rejects_default_internal_key_in_production() -> None:
    with pytest.raises(ValidationError, match="must be changed"):
        SampleCRMSettings(_env_file=None, app_env="production")


def test_reference_agent_requires_key_for_enabled_provider() -> None:
    with pytest.raises(ValidationError, match="LLM_API_KEY"):
        ReferenceAgentSettings(_env_file=None, app_env="test", llm_provider="real-provider")
