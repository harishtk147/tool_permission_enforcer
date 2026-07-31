from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from services.common.database import Database
from services.common.settings import (
    PermissionProxySettings,
    ReferenceAgentSettings,
    SampleCRMSettings,
)
from services.permission_proxy.main import create_app as create_proxy_app
from services.reference_agent.main import create_app as create_agent_app
from services.sample_crm.main import create_app as create_crm_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize(
    ("factory", "settings", "expected_service"),
    [
        (
            create_proxy_app,
            PermissionProxySettings(
                _env_file=None,
                app_env="test",
                database_url="sqlite+pysqlite:///:memory:",
            ),
            "permission-proxy",
        ),
        (
            create_crm_app,
            SampleCRMSettings(
                _env_file=None,
                app_env="test",
                database_url="sqlite+pysqlite:///:memory:",
                internal_api_key="test-only-internal-api-key-long-enough",
            ),
            "sample-crm",
        ),
        (
            create_agent_app,
            ReferenceAgentSettings(_env_file=None, app_env="test"),
            "reference-agent",
        ),
    ],
)
@pytest.mark.anyio
async def test_service_health_endpoints(
    factory: Callable[..., FastAPI],
    settings: PermissionProxySettings | SampleCRMSettings | ReferenceAgentSettings,
    expected_service: str,
) -> None:
    app = factory(settings=settings)
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        live_response = await client.get("/health/live")
        ready_response = await client.get("/health/ready")

    assert live_response.status_code == 200
    assert live_response.json()["status"] == "alive"
    assert live_response.json()["service"] == expected_service
    assert ready_response.status_code == 200
    assert ready_response.json()["status"] == "ready"
    assert ready_response.json()["checks"]["configuration"] == "ok"
    if expected_service != "reference-agent":
        assert ready_response.json()["checks"]["database"] == "ok"


@pytest.mark.anyio
async def test_proxy_root_exposes_service_metadata() -> None:
    settings = PermissionProxySettings(
        _env_file=None,
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
    )
    app = create_proxy_app(settings=settings)
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "permission-proxy",
        "version": "0.1.0",
        "environment": "test",
        "docs_url": "/docs",
    }


@pytest.mark.anyio
async def test_proxy_readiness_fails_when_database_is_unavailable(
    tmp_path: Path,
) -> None:
    database_url = (
        f"sqlite+pysqlite:///{(tmp_path / 'missing-parent' / 'unavailable.db').as_posix()}"
    )
    settings = PermissionProxySettings(
        _env_file=None,
        app_env="test",
        database_url=database_url,
    )
    database = Database(database_url)
    app = create_proxy_app(settings=settings, database=database)
    transport = httpx.ASGITransport(app=app)

    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        ):
            response = await client.get("/health/ready")
    finally:
        database.dispose()

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["database"] == "unavailable"
