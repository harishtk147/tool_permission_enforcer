import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config

from services.common.database import Database
from services.common.settings import PermissionProxySettings
from services.permission_proxy.domain.enums import AgentStatus
from services.permission_proxy.domain.models import Agent
from services.permission_proxy.main import create_app
from services.permission_proxy.persistence.repositories import AgentRepository, SessionRepository
from services.permission_proxy.persistence.seed import SEED_AGENT_ID, seed_phase_1
from services.permission_proxy.security.auth import AccessTokenService

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def migrate(database_url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    previous_url = os.environ.get("PROXY_DATABASE_URL")
    os.environ["PROXY_DATABASE_URL"] = database_url
    try:
        command.upgrade(config, "head")
    finally:
        if previous_url is None:
            os.environ.pop("PROXY_DATABASE_URL", None)
        else:
            os.environ["PROXY_DATABASE_URL"] = previous_url


@pytest.fixture
def phase_2_environment(
    tmp_path: Path,
) -> Iterator[tuple[PermissionProxySettings, Database]]:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'phase-2.db').as_posix()}"
    migrate(database_url)
    database = Database(database_url)
    seed_phase_1(database)
    settings = PermissionProxySettings(
        _env_file=None,
        app_env="test",
        database_url=database_url,
        dev_auth_enabled=True,
    )
    yield settings, database
    database.dispose()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_trusted_session_create_validate_revoke_flow(
    phase_2_environment: tuple[PermissionProxySettings, Database],
) -> None:
    settings, database = phase_2_environment
    tokens = AccessTokenService(settings)
    host_token = tokens.issue_development_token(
        subject="dev:trusted-host",
        token_use="host",
        scopes={"session:create", "session:revoke"},
    )
    agent_token = tokens.issue_development_token(
        subject="dev:agent_support_001",
        token_use="agent",
        scopes={"tool:invoke"},
    )
    app = create_app(settings=settings, database=database)
    transport = httpx.ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        missing_auth = await client.get("/v1/identity/me")
        assert missing_auth.status_code == 401

        agent_identity = await client.get("/v1/identity/me", headers=bearer(agent_token))
        assert agent_identity.status_code == 200
        assert agent_identity.json()["agent_id"] == SEED_AGENT_ID

        create_response = await client.post(
            "/v1/sessions",
            headers=bearer(host_token),
            json={
                "agent_id": SEED_AGENT_ID,
                "user_id": "user_123",
                "customer_id": "customer_1001",
                "ttl_seconds": 300,
            },
        )
        assert create_response.status_code == 201
        created = create_response.json()

        validate_response = await client.post(
            "/v1/sessions/validate",
            headers=bearer(agent_token),
            json={"session_token": created["session_token"]},
        )
        assert validate_response.status_code == 200
        assert validate_response.json()["customer_id"] == "customer_1001"

        revoke_response = await client.post(
            f"/v1/sessions/{created['session_id']}/revoke",
            headers=bearer(host_token),
        )
        assert revoke_response.status_code == 200
        assert revoke_response.json()["status"] == "revoked"

        revoked_validation = await client.post(
            "/v1/sessions/validate",
            headers=bearer(agent_token),
            json={"session_token": created["session_token"]},
        )
        assert revoked_validation.status_code == 401
        assert revoked_validation.json()["detail"]["code"] == "SESSION_NOT_ACTIVE"

    with database.session() as session:
        persisted = SessionRepository(session).get(created["session_id"])
        assert persisted is not None
        assert persisted.created_by_subject == "dev:trusted-host"


@pytest.mark.anyio
async def test_session_rejects_insufficient_scope_wrong_agent_and_tampering(
    phase_2_environment: tuple[PermissionProxySettings, Database],
) -> None:
    settings, database = phase_2_environment
    tokens = AccessTokenService(settings)
    host_without_scope = tokens.issue_development_token(
        subject="dev:trusted-host",
        token_use="host",
        scopes=set(),
    )
    host_token = tokens.issue_development_token(
        subject="dev:trusted-host",
        token_use="host",
        scopes={"session:create"},
    )
    agent_token = tokens.issue_development_token(
        subject="dev:agent_support_001",
        token_use="agent",
        scopes={"tool:invoke"},
    )
    with database.session() as session:
        AgentRepository(session).add(
            Agent(
                agent_id="agent_support_002",
                oidc_subject="dev:agent_support_002",
                name="Second Support Agent",
                owning_team="Customer Support Engineering",
                status=AgentStatus.ACTIVE,
            )
        )
    second_agent_token = tokens.issue_development_token(
        subject="dev:agent_support_002",
        token_use="agent",
        scopes={"tool:invoke"},
    )
    app = create_app(settings=settings, database=database)
    transport = httpx.ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        denied_create = await client.post(
            "/v1/sessions",
            headers=bearer(host_without_scope),
            json={
                "agent_id": SEED_AGENT_ID,
                "user_id": "user_123",
                "customer_id": "customer_1001",
            },
        )
        assert denied_create.status_code == 403
        assert denied_create.json()["detail"]["code"] == "INSUFFICIENT_SCOPE"

        create_response = await client.post(
            "/v1/sessions",
            headers=bearer(host_token),
            json={
                "agent_id": SEED_AGENT_ID,
                "user_id": "user_123",
                "customer_id": "customer_1001",
            },
        )
        assert create_response.status_code == 201
        session_token = create_response.json()["session_token"]

        wrong_agent = await client.post(
            "/v1/sessions/validate",
            headers=bearer(second_agent_token),
            json={"session_token": session_token},
        )
        assert wrong_agent.status_code == 403
        assert wrong_agent.json()["detail"]["code"] == "SESSION_AGENT_MISMATCH"

        header, payload, signature = session_token.split(".")
        replacement = "A" if signature[0] != "A" else "B"
        tampered_token = ".".join((header, payload, f"{replacement}{signature[1:]}"))
        tampered = await client.post(
            "/v1/sessions/validate",
            headers=bearer(agent_token),
            json={"session_token": tampered_token},
        )
        assert tampered.status_code == 401
        assert tampered.json()["detail"]["code"] == "INVALID_SESSION_TOKEN"


@pytest.mark.anyio
async def test_suspended_agent_and_server_side_expiry_are_enforced(
    phase_2_environment: tuple[PermissionProxySettings, Database],
) -> None:
    settings, database = phase_2_environment
    tokens = AccessTokenService(settings)
    host_token = tokens.issue_development_token(
        subject="dev:trusted-host",
        token_use="host",
        scopes={"session:create"},
    )
    agent_token = tokens.issue_development_token(
        subject="dev:agent_support_001",
        token_use="agent",
        scopes={"tool:invoke"},
    )
    app = create_app(settings=settings, database=database)
    transport = httpx.ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        created = (
            await client.post(
                "/v1/sessions",
                headers=bearer(host_token),
                json={
                    "agent_id": SEED_AGENT_ID,
                    "user_id": "user_123",
                    "customer_id": "customer_1001",
                },
            )
        ).json()

        with database.session() as session:
            persisted = SessionRepository(session).get(created["session_id"])
            assert persisted is not None
            persisted.created_at = datetime.now(UTC) - timedelta(hours=1)
            persisted.expires_at = datetime.now(UTC) - timedelta(seconds=1)

        expired = await client.post(
            "/v1/sessions/validate",
            headers=bearer(agent_token),
            json={"session_token": created["session_token"]},
        )
        assert expired.status_code == 401
        assert expired.json()["detail"]["code"] == "SESSION_EXPIRED"

        with database.session() as session:
            agent = AgentRepository(session).get(SEED_AGENT_ID)
            assert agent is not None
            agent.status = AgentStatus.SUSPENDED

        suspended_identity = await client.get(
            "/v1/identity/me",
            headers=bearer(agent_token),
        )
        assert suspended_identity.status_code == 403
        assert suspended_identity.json()["detail"]["code"] == "AGENT_NOT_ACTIVE"
