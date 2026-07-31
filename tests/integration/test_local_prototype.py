import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import update

from services.common.database import Database
from services.common.settings import PermissionProxySettings, SampleCRMSettings
from services.permission_proxy.audit.service import AuditService
from services.permission_proxy.domain.models import ToolCallAuditEvent
from services.permission_proxy.main import create_app as create_proxy_app
from services.permission_proxy.persistence.seed import SEED_AGENT_ID, seed_phase_1
from services.permission_proxy.security.auth import AccessTokenService
from services.permission_proxy.tools.crm import HTTPCRMAdapter
from services.sample_crm.main import create_app as create_crm_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INTERNAL_KEY = "test-internal-api-key-that-is-long-enough"


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
def prototype_environment(
    tmp_path: Path,
) -> Iterator[tuple[PermissionProxySettings, SampleCRMSettings, Database]]:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'prototype.db').as_posix()}"
    migrate(database_url)
    database = Database(database_url)
    seed_phase_1(database)
    proxy_settings = PermissionProxySettings(
        _env_file=None,
        app_env="test",
        database_url=database_url,
        crm_internal_api_key=INTERNAL_KEY,
        dev_auth_enabled=True,
    )
    crm_settings = SampleCRMSettings(
        _env_file=None,
        app_env="test",
        database_url=database_url,
        internal_api_key=INTERNAL_KEY,
    )
    yield proxy_settings, crm_settings, database
    database.dispose()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_read_only_policy_proxy_crm_and_audit_flow(
    prototype_environment: tuple[
        PermissionProxySettings,
        SampleCRMSettings,
        Database,
    ],
) -> None:
    proxy_settings, crm_settings, database = prototype_environment
    crm_app = create_crm_app(settings=crm_settings, database=database)
    crm_transport = httpx.ASGITransport(app=crm_app)
    proxy_app = create_proxy_app(
        settings=proxy_settings,
        database=database,
        tool_adapter=HTTPCRMAdapter(proxy_settings, transport=crm_transport),
    )
    tokens = AccessTokenService(proxy_settings)
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
    auditor_token = tokens.issue_development_token(
        subject="dev:auditor",
        token_use="auditor",
        scopes={"audit:read"},
    )

    async with (
        crm_app.router.lifespan_context(crm_app),
        proxy_app.router.lifespan_context(proxy_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=proxy_app),
            base_url="http://proxy",
        ) as client,
    ):
        created = await client.post(
            "/v1/sessions",
            headers=bearer(host_token),
            json={
                "agent_id": SEED_AGENT_ID,
                "user_id": "user_local_demo",
                "customer_id": "customer_1001",
                "ttl_seconds": 600,
            },
        )
        assert created.status_code == 201
        session_token = created.json()["session_token"]
        call_headers = {
            **bearer(agent_token),
            "X-Session-Token": session_token,
        }

        allowed = await client.post(
            "/v1/tool-calls",
            headers={**call_headers, "Idempotency-Key": "demo-read-001"},
            json={
                "tool": "crm",
                "operation": "read_customer",
                "parameters": {"customer_id": "customer_1001"},
            },
        )
        assert allowed.status_code == 200
        assert allowed.json()["decision"] == "allow"
        assert allowed.json()["result"]["support_tier"] == "gold"

        blocked_write = await client.post(
            "/v1/tool-calls",
            headers={**call_headers, "Idempotency-Key": "demo-write-001"},
            json={
                "tool": "crm",
                "operation": "write_customer",
                "parameters": {
                    "customer_id": "customer_1001",
                    "changes": {"address": "Attacker-controlled address"},
                },
            },
        )
        assert blocked_write.status_code == 403
        assert blocked_write.json()["reason_code"] == "OPERATION_NOT_ALLOWED"

        blocked_cross_customer = await client.post(
            "/v1/tool-calls",
            headers={**call_headers, "Idempotency-Key": "demo-cross-001"},
            json={
                "tool": "crm",
                "operation": "read_customer",
                "parameters": {"customer_id": "customer_1002"},
            },
        )
        assert blocked_cross_customer.status_code == 403
        assert blocked_cross_customer.json()["reason_code"] == "DATA_SCOPE_VIOLATION"

        blocked_delete = await client.post(
            "/v1/tool-calls",
            headers={**call_headers, "Idempotency-Key": "demo-delete-001"},
            json={
                "tool": "crm",
                "operation": "delete_customer",
                "parameters": {"customer_id": "customer_1001"},
            },
        )
        assert blocked_delete.status_code == 403
        assert blocked_delete.json()["reason_code"] == "OPERATION_NOT_ALLOWED"

        duplicate = await client.post(
            "/v1/tool-calls",
            headers={**call_headers, "Idempotency-Key": "demo-read-001"},
            json={
                "tool": "crm",
                "operation": "read_customer",
                "parameters": {"customer_id": "customer_1001"},
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["reason_code"] == "DUPLICATE_REQUEST"

        audit_response = await client.get(
            "/v1/audit/events",
            headers=bearer(auditor_token),
        )
        assert audit_response.status_code == 200
        events = audit_response.json()["events"]
        assert len(events) == 6
        assert {event["reason_code"] for event in events} >= {
            "ALLOWED",
            "OPERATION_NOT_ALLOWED",
            "DATA_SCOPE_VIOLATION",
            "DUPLICATE_REQUEST",
        }
        write_event = next(
            event for event in events if event["idempotency_key"] == "demo-write-001"
        )
        assert write_event["sanitized_parameters"]["changes"] == "[REDACTED]"
        assert "Attacker-controlled address" not in str(write_event)

        request_events = await client.get(
            f"/v1/audit/events/{allowed.json()['request_id']}",
            headers=bearer(auditor_token),
        )
        assert request_events.status_code == 200
        assert [event["execution_status"] for event in request_events.json()] == [
            "authorized",
            "executed",
        ]

        integrity = await client.get(
            "/v1/audit/integrity",
            headers=bearer(auditor_token),
        )
        assert integrity.status_code == 200
        assert integrity.json() == {
            "valid": True,
            "events_checked": 6,
            "first_invalid_event_id": None,
        }

    async with httpx.AsyncClient(
        transport=crm_transport,
        base_url="http://crm",
    ) as crm_client:
        direct_without_key = await crm_client.get("/customers/customer_1001")
        assert direct_without_key.status_code == 401
        persisted = await crm_client.get(
            "/customers/customer_1001",
            headers={"X-Internal-API-Key": INTERNAL_KEY},
        )
        assert persisted.status_code == 200
        assert persisted.json()["address"] == "101 Synthetic Avenue, Bengaluru"


@pytest.mark.anyio
async def test_sample_crm_read_write_delete_operations_are_functional(
    prototype_environment: tuple[
        PermissionProxySettings,
        SampleCRMSettings,
        Database,
    ],
) -> None:
    _, crm_settings, database = prototype_environment
    app = create_crm_app(settings=crm_settings, database=database)
    headers = {"X-Internal-API-Key": INTERNAL_KEY}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://crm",
    ) as client:
        read = await client.get("/customers/customer_1003", headers=headers)
        assert read.status_code == 200

        updated = await client.patch(
            "/customers/customer_1003",
            headers=headers,
            json={"support_tier": "gold"},
        )
        assert updated.status_code == 200
        assert updated.json()["support_tier"] == "gold"

        deleted = await client.delete("/customers/customer_1003", headers=headers)
        assert deleted.status_code == 204
        missing = await client.get("/customers/customer_1003", headers=headers)
        assert missing.status_code == 404


def test_audit_integrity_verification_detects_database_tampering(
    prototype_environment: tuple[
        PermissionProxySettings,
        SampleCRMSettings,
        Database,
    ],
) -> None:
    _, _, database = prototype_environment
    audit = AuditService(database)
    from services.permission_proxy.audit.service import AuditEventInput
    from services.permission_proxy.domain.enums import AuditDecision, AuditExecutionStatus

    audit.record(
        AuditEventInput(
            request_id="req_tamper_test",
            idempotency_key="tamper-key-001",
            sequence=0,
            agent_id=SEED_AGENT_ID,
            session_id=None,
            user_id=None,
            tool="crm",
            operation="read_customer",
            parameters={"customer_id": "customer_1001"},
            decision=AuditDecision.ALLOW,
            reason_code="ALLOWED",
            execution_status=AuditExecutionStatus.AUTHORIZED,
        )
    )
    assert audit.verify_integrity().valid is True

    with database.session() as session:
        session.execute(
            update(ToolCallAuditEvent)
            .where(ToolCallAuditEvent.request_id == "req_tamper_test")
            .values(reason_code="TAMPERED")
        )

    result = audit.verify_integrity()
    assert result.valid is False
    assert result.first_invalid_event_id is not None
