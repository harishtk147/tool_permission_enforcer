import copy
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from services.common.database import Database
from services.permission_proxy.domain.enums import (
    AuditDecision,
    AuditExecutionStatus,
    ManifestStatus,
    SessionStatus,
)
from services.permission_proxy.domain.exceptions import (
    InvalidManifestStateError,
    SeedDataConflictError,
)
from services.permission_proxy.domain.models import (
    AgentSession,
    PermissionManifest,
    ToolCallAuditEvent,
)
from services.permission_proxy.persistence.repositories import (
    AgentRepository,
    AuditEventRepository,
    ManifestRepository,
    SessionRepository,
    ToolDefinitionRepository,
    manifest_checksum,
)
from services.permission_proxy.persistence.seed import (
    READ_ONLY_MANIFEST,
    SEED_AGENT_ID,
    SEED_MANIFEST_ID,
    seed_phase_1,
)
from services.sample_crm.persistence.repositories import CustomerRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TABLES = {
    "agents",
    "agent_sessions",
    "alembic_version",
    "crm_customers",
    "permission_manifests",
    "tool_call_audit_events",
    "tool_definitions",
}


def run_migration(database_url: str, revision: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)

    previous_url = os.environ.get("PROXY_DATABASE_URL")
    os.environ["PROXY_DATABASE_URL"] = database_url
    try:
        if revision == "base":
            command.downgrade(config, revision)
        else:
            command.upgrade(config, revision)
    finally:
        if previous_url is None:
            os.environ.pop("PROXY_DATABASE_URL", None)
        else:
            os.environ["PROXY_DATABASE_URL"] = previous_url


@pytest.fixture
def migrated_database(tmp_path: Path) -> Iterator[tuple[Database, str]]:
    database_path = tmp_path / "phase-1.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    run_migration(database_url, "head")
    database = Database(database_url)
    try:
        yield database, database_url
    finally:
        database.dispose()


def test_initial_migration_creates_and_downgrades_expected_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"

    run_migration(database_url, "head")
    database = Database(database_url)
    assert set(inspect(database.engine).get_table_names()) == EXPECTED_TABLES
    database.dispose()

    run_migration(database_url, "base")
    downgraded_database = Database(database_url)
    remaining_tables = set(inspect(downgraded_database.engine).get_table_names())
    downgraded_database.dispose()

    assert remaining_tables <= {"alembic_version"}


def test_seed_is_idempotent_and_survives_engine_restart(
    migrated_database: tuple[Database, str],
) -> None:
    database, database_url = migrated_database

    first_summary = seed_phase_1(database)
    second_summary = seed_phase_1(database)
    assert first_summary == second_summary
    assert first_summary.agents == 1
    assert first_summary.tools == 1
    assert first_summary.manifests == 1
    assert first_summary.customers == 3

    database.dispose()
    restarted_database = Database(database_url)
    try:
        with restarted_database.session() as session:
            agents = AgentRepository(session)
            tools = ToolDefinitionRepository(session)
            manifests = ManifestRepository(session)
            customers = CustomerRepository(session)

            assert agents.get(SEED_AGENT_ID) is not None
            assert tools.get_by_name("crm") is not None
            assert customers.get("customer_1001") is not None
            assert manifests.get_active(SEED_AGENT_ID) is not None
    finally:
        restarted_database.dispose()


def test_manifest_activation_is_atomic_and_rollback_safe(
    migrated_database: tuple[Database, str],
) -> None:
    database, _ = migrated_database
    seed_phase_1(database)

    version_2_document = copy.deepcopy(READ_ONLY_MANIFEST)
    version_2_document["manifest_id"] = "support-agent-readonly-v2"
    with pytest.raises(IntegrityError), database.session() as session:
        ManifestRepository(session).add(
            PermissionManifest(
                manifest_id="illegal-second-active-manifest",
                agent_id=SEED_AGENT_ID,
                version=99,
                status=ManifestStatus.ACTIVE,
                document=version_2_document,
                checksum=manifest_checksum(version_2_document),
                effective_from=datetime(2026, 9, 1, tzinfo=UTC),
                expires_at=None,
                created_by="integration-test",
                approved_by="integration-test",
                change_reason="Prove database rejects a second active manifest",
            )
        )

    with database.session() as session:
        manifests = ManifestRepository(session)
        manifests.add(
            PermissionManifest(
                manifest_id="support-agent-readonly-v2",
                agent_id=SEED_AGENT_ID,
                version=2,
                status=ManifestStatus.DRAFT,
                document=version_2_document,
                checksum=manifest_checksum(version_2_document),
                effective_from=datetime(2026, 9, 1, tzinfo=UTC),
                expires_at=None,
                created_by="integration-test",
                approved_by=None,
                change_reason="Verify atomic manifest replacement",
            )
        )
        manifests.activate("support-agent-readonly-v2", approved_by="test-reviewer")

    with database.session() as session:
        manifests = ManifestRepository(session)
        original = manifests.get(SEED_MANIFEST_ID)
        active = manifests.get_active(SEED_AGENT_ID)
        assert original is not None
        assert active is not None
        assert original.status == ManifestStatus.SUPERSEDED
        assert active.manifest_id == "support-agent-readonly-v2"

    version_3_document = copy.deepcopy(READ_ONLY_MANIFEST)
    version_3_document["manifest_id"] = "support-agent-readonly-v3"
    with database.session() as session:
        ManifestRepository(session).add(
            PermissionManifest(
                manifest_id="support-agent-readonly-v3",
                agent_id=SEED_AGENT_ID,
                version=3,
                status=ManifestStatus.DRAFT,
                document=version_3_document,
                checksum=manifest_checksum(version_3_document),
                effective_from=datetime(2026, 10, 1, tzinfo=UTC),
                expires_at=None,
                created_by="integration-test",
                approved_by=None,
                change_reason="Verify transaction rollback",
            )
        )

    with pytest.raises(RuntimeError, match="simulated failure"), database.session() as session:
        ManifestRepository(session).activate(
            "support-agent-readonly-v3",
            approved_by="test-reviewer",
        )
        raise RuntimeError("simulated failure after activation")

    with database.session() as session:
        manifests = ManifestRepository(session)
        active = manifests.get_active(SEED_AGENT_ID)
        rolled_back = manifests.get("support-agent-readonly-v3")
        assert active is not None
        assert rolled_back is not None
        assert active.manifest_id == "support-agent-readonly-v2"
        assert rolled_back.status == ManifestStatus.DRAFT
        with pytest.raises(InvalidManifestStateError):
            manifests.activate(SEED_MANIFEST_ID, approved_by="test-reviewer")


def test_session_and_audit_repositories_persist_records(
    migrated_database: tuple[Database, str],
) -> None:
    database, _ = migrated_database
    seed_phase_1(database)
    now = datetime.now(UTC)

    with database.session() as session:
        sessions = SessionRepository(session)
        audits = AuditEventRepository(session)
        agent_session = sessions.add(
            AgentSession(
                session_id="sess_phase_1",
                token_jti="jti_phase_1",
                agent_id=SEED_AGENT_ID,
                user_id="user_phase_1",
                customer_id="customer_1001",
                created_by_subject="phase-1-test-host",
                status=SessionStatus.ACTIVE,
                created_at=now,
                expires_at=now + timedelta(minutes=30),
                revoked_at=None,
            )
        )
        assert sessions.get(agent_session.session_id) is not None
        assert sessions.count() == 1

        audits.add(
            ToolCallAuditEvent(
                event_id="audit_phase_1",
                request_id="request_phase_1",
                idempotency_key="idempotency_phase_1",
                sequence=1,
                timestamp=now,
                agent_id=SEED_AGENT_ID,
                session_id=agent_session.session_id,
                user_id="user_phase_1",
                tool="crm",
                operation="read_customer",
                sanitized_parameters={"customer_id": "customer_1001"},
                decision=AuditDecision.ALLOW,
                reason_code="ALLOW",
                matched_manifest_id=SEED_MANIFEST_ID,
                policy_checksum=manifest_checksum(READ_ONLY_MANIFEST),
                execution_status=AuditExecutionStatus.AUTHORIZED,
                upstream_status_code=None,
                decision_latency_ms=5,
                total_latency_ms=None,
                trace_id="trace_phase_1",
                previous_record_hash=None,
                record_hash="a" * 64,
            )
        )
        assert audits.count() == 1


def test_seed_rejects_conflicting_existing_identifiers(
    migrated_database: tuple[Database, str],
) -> None:
    database, _ = migrated_database
    seed_phase_1(database)

    with database.session() as session:
        agent = AgentRepository(session).get(SEED_AGENT_ID)
        assert agent is not None
        agent.oidc_subject = "unexpected:subject"

    with pytest.raises(SeedDataConflictError, match="OIDC subject"):
        seed_phase_1(database)
