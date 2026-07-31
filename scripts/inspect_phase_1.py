import argparse
import json

from services.common.database import Database
from services.common.settings import PermissionProxySettings
from services.permission_proxy.persistence.repositories import (
    AgentRepository,
    AuditEventRepository,
    ManifestRepository,
    SessionRepository,
    ToolDefinitionRepository,
)
from services.permission_proxy.persistence.seed import SEED_AGENT_ID
from services.sample_crm.persistence.repositories import CustomerRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect persisted Phase 1 records")
    parser.add_argument(
        "--database-url",
        help="Override PROXY_DATABASE_URL for this inspection",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database_url = args.database_url or PermissionProxySettings().database_url
    database = Database(database_url)
    try:
        with database.session() as session:
            active_manifest = ManifestRepository(session).get_active(SEED_AGENT_ID)
            result = {
                "agents": AgentRepository(session).count(),
                "tools": ToolDefinitionRepository(session).count(),
                "manifests": ManifestRepository(session).count(),
                "sessions": SessionRepository(session).count(),
                "audit_events": AuditEventRepository(session).count(),
                "customers": CustomerRepository(session).count(),
                "active_manifest_id": (
                    active_manifest.manifest_id if active_manifest is not None else None
                ),
                "database_ready": database.ping(),
            }
    finally:
        database.dispose()

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
