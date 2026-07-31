from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from services.common.database import Database
from services.permission_proxy.domain.enums import (
    AgentStatus,
    ManifestStatus,
    ToolStatus,
)
from services.permission_proxy.domain.exceptions import SeedDataConflictError
from services.permission_proxy.domain.models import Agent, PermissionManifest, ToolDefinition
from services.permission_proxy.persistence.repositories import (
    AgentRepository,
    ManifestRepository,
    ToolDefinitionRepository,
    manifest_checksum,
)
from services.sample_crm.domain.models import CRMCustomer
from services.sample_crm.persistence.repositories import CustomerRepository

SEED_AGENT_ID = "agent_support_001"
SEED_TOOL_ID = "tool_crm_001"
SEED_MANIFEST_ID = "support-agent-readonly-v1"

READ_ONLY_MANIFEST: dict[str, Any] = {
    "schema_version": "1.0",
    "manifest_id": SEED_MANIFEST_ID,
    "agent_id": SEED_AGENT_ID,
    "tools": {
        "crm": {
            "allowed_operations": ["read_customer"],
            "operation_rules": {
                "read_customer": {
                    "parameter_schema": {
                        "required": ["customer_id"],
                        "properties": {"customer_id": {"type": "string"}},
                    },
                    "data_scope": {
                        "all": [
                            {
                                "type": "session_value_equals_parameter",
                                "session_claim": "customer_id",
                                "parameter": "customer_id",
                            }
                        ]
                    },
                }
            },
        }
    },
    "deny_message": "This operation is not permitted for the current agent and session.",
}

CRM_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["customer_id"],
    "properties": {
        "customer_id": {"type": "string", "maxLength": 64},
        "changes": {"type": "object"},
    },
    "additionalProperties": False,
}

CRM_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["customer_id"],
    "properties": {
        "customer_id": {"type": "string"},
        "name": {"type": "string"},
        "email": {"type": "string"},
        "support_tier": {"type": "string"},
        "address": {"type": "string"},
    },
}

SEED_CUSTOMERS = (
    {
        "customer_id": "customer_1001",
        "name": "Asha Rao",
        "email": "asha.rao@example.invalid",
        "support_tier": "gold",
        "address": "101 Synthetic Avenue, Bengaluru",
    },
    {
        "customer_id": "customer_1002",
        "name": "Vikram Shah",
        "email": "vikram.shah@example.invalid",
        "support_tier": "silver",
        "address": "202 Demonstration Road, Pune",
    },
    {
        "customer_id": "customer_1003",
        "name": "Meera Nair",
        "email": "meera.nair@example.invalid",
        "support_tier": "standard",
        "address": "303 Example Street, Kochi",
    },
)


@dataclass(frozen=True)
class SeedSummary:
    agents: int
    tools: int
    manifests: int
    customers: int
    active_manifest_id: str


def _assert_equal(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise SeedDataConflictError(
            f"Existing seed entity has unexpected {label}: {actual!r} != {expected!r}"
        )


def seed_phase_1(database: Database) -> SeedSummary:
    """Create deterministic synthetic Phase 1 data in one transaction."""

    with database.session() as session:
        agents = AgentRepository(session)
        tools = ToolDefinitionRepository(session)
        manifests = ManifestRepository(session)
        customers = CustomerRepository(session)

        agent = agents.get(SEED_AGENT_ID)
        if agent is None:
            agent = agents.add(
                Agent(
                    agent_id=SEED_AGENT_ID,
                    oidc_subject="dev:agent_support_001",
                    name="Read-only Support Agent",
                    owning_team="Customer Support Engineering",
                    status=AgentStatus.ACTIVE,
                )
            )
        else:
            _assert_equal("OIDC subject", agent.oidc_subject, "dev:agent_support_001")

        tool = tools.get(SEED_TOOL_ID)
        if tool is None:
            tools.add(
                ToolDefinition(
                    tool_id=SEED_TOOL_ID,
                    name="crm",
                    adapter_type="http_crm_v1",
                    private_base_url="http://sample-crm:8001",
                    allowed_operations=[
                        "read_customer",
                        "write_customer",
                        "delete_customer",
                    ],
                    request_schema=CRM_REQUEST_SCHEMA,
                    response_schema=CRM_RESPONSE_SCHEMA,
                    status=ToolStatus.ACTIVE,
                )
            )
        else:
            _assert_equal("tool name", tool.name, "crm")

        expected_checksum = manifest_checksum(READ_ONLY_MANIFEST)
        manifest = manifests.get(SEED_MANIFEST_ID)
        if manifest is None:
            manifest = manifests.add(
                PermissionManifest(
                    manifest_id=SEED_MANIFEST_ID,
                    agent_id=SEED_AGENT_ID,
                    version=1,
                    status=ManifestStatus.DRAFT,
                    document=READ_ONLY_MANIFEST,
                    checksum=expected_checksum,
                    effective_from=datetime(2026, 1, 1, tzinfo=UTC),
                    expires_at=None,
                    created_by="phase-1-seed",
                    approved_by=None,
                    change_reason="Initial read-only support-agent manifest",
                )
            )
        else:
            _assert_equal("manifest checksum", manifest.checksum, expected_checksum)

        for customer_data in SEED_CUSTOMERS:
            customer_id = customer_data["customer_id"]
            customer = customers.get(customer_id)
            if customer is None:
                customers.add(CRMCustomer(**customer_data))
            else:
                _assert_equal("customer name", customer.name, customer_data["name"])

        if manifest.status == ManifestStatus.DRAFT:
            manifest = manifests.activate(manifest.manifest_id, approved_by="phase-1-seed")

        summary = SeedSummary(
            agents=agents.count(),
            tools=tools.count(),
            manifests=manifests.count(),
            customers=customers.count(),
            active_manifest_id=manifest.manifest_id,
        )

    return summary
