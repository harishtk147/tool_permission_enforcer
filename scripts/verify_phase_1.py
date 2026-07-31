import os
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from services.common.database import Database
from services.permission_proxy.persistence.repositories import (
    AgentRepository,
    ManifestRepository,
    ToolDefinitionRepository,
)
from services.permission_proxy.persistence.seed import SEED_AGENT_ID, seed_phase_1
from services.sample_crm.persistence.repositories import CustomerRepository

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def upgrade(database_url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)

    previous_url = os.environ.get("PROXY_DATABASE_URL")
    os.environ["PROXY_DATABASE_URL"] = database_url
    try:
        command.upgrade(config, "head")
        command.check(config)
    finally:
        if previous_url is None:
            os.environ.pop("PROXY_DATABASE_URL", None)
        else:
            os.environ["PROXY_DATABASE_URL"] = previous_url


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="permission-phase-1-") as temp_directory:
        database_path = Path(temp_directory) / "phase-1-verification.db"
        database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
        upgrade(database_url)

        database = Database(database_url)
        first_summary = seed_phase_1(database)
        second_summary = seed_phase_1(database)
        database.dispose()

        if first_summary != second_summary:
            raise RuntimeError("Seed data is not idempotent")

        restarted_database = Database(database_url)
        try:
            expected_tables = {
                "agents",
                "agent_sessions",
                "alembic_version",
                "crm_customers",
                "permission_manifests",
                "tool_call_audit_events",
                "tool_definitions",
            }
            actual_tables = set(inspect(restarted_database.engine).get_table_names())
            if expected_tables != actual_tables:
                raise RuntimeError(
                    f"Unexpected migrated tables: expected {expected_tables}, got {actual_tables}"
                )

            with restarted_database.session() as session:
                agents = AgentRepository(session)
                tools = ToolDefinitionRepository(session)
                manifests = ManifestRepository(session)
                customers = CustomerRepository(session)

                if agents.get(SEED_AGENT_ID) is None:
                    raise RuntimeError("Seed agent did not survive database restart")
                if agents.count() != 1 or tools.count() != 1:
                    raise RuntimeError("Unexpected Phase 1 control-plane seed counts")
                if manifests.count() != 1 or customers.count() != 3:
                    raise RuntimeError("Unexpected manifest or CRM seed counts")
                if manifests.get_active(SEED_AGENT_ID) is None:
                    raise RuntimeError("No active manifest found after database restart")
        finally:
            restarted_database.dispose()

        print("Phase 1 migration, idempotent seed, and restart persistence checks passed.")


if __name__ == "__main__":
    main()
