from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from services.common.database import Database
from services.permission_proxy.domain.enums import ToolStatus
from services.permission_proxy.persistence.repositories import (
    ManifestRepository,
    ToolDefinitionRepository,
    manifest_checksum,
)
from services.permission_proxy.policy.manifest import ManifestDocument, validate_parameters
from services.permission_proxy.security.sessions import TrustedSessionClaims, as_utc


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason_code: str
    message: str
    manifest_id: str | None = None
    policy_checksum: str | None = None


class PolicyEvaluator:
    """Side-effect-free, first-failure, default-deny policy evaluation."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def evaluate(
        self,
        *,
        agent_id: str,
        session: TrustedSessionClaims,
        tool_name: str,
        operation: str,
        parameters: dict[str, Any],
        now: datetime | None = None,
    ) -> PolicyDecision:
        evaluated_at = now or datetime.now(UTC)
        with self.database.session() as database_session:
            manifest = ManifestRepository(database_session).get_active(agent_id)
            if manifest is None:
                return self._deny("MANIFEST_NOT_FOUND", "No active permission manifest exists")
            if as_utc(manifest.effective_from) > evaluated_at or (
                manifest.expires_at is not None and as_utc(manifest.expires_at) <= evaluated_at
            ):
                return self._deny(
                    "MANIFEST_EXPIRED",
                    "The active manifest is outside its effective window",
                    manifest.manifest_id,
                    manifest.checksum,
                )
            if manifest_checksum(manifest.document) != manifest.checksum:
                return self._deny(
                    "POLICY_INTEGRITY_VIOLATION",
                    "The active manifest failed its integrity check",
                    manifest.manifest_id,
                    manifest.checksum,
                )
            try:
                document = ManifestDocument.model_validate(manifest.document)
            except ValidationError:
                return self._deny(
                    "POLICY_CONFIGURATION_INVALID",
                    "The active manifest is invalid",
                    manifest.manifest_id,
                    manifest.checksum,
                )
            if (
                document.manifest_id != manifest.manifest_id
                or document.agent_id != manifest.agent_id
            ):
                return self._deny(
                    "POLICY_CONFIGURATION_INVALID",
                    "The active manifest identity is invalid",
                    manifest.manifest_id,
                    manifest.checksum,
                )

            tool = ToolDefinitionRepository(database_session).get_by_name(tool_name)
            if tool is None or tool.status != ToolStatus.ACTIVE:
                return self._deny(
                    "TOOL_NOT_REGISTERED",
                    "The requested tool is not registered",
                    manifest.manifest_id,
                    manifest.checksum,
                )
            tool_policy = document.tools.get(tool_name)
            if tool_policy is None:
                return self._deny(
                    "TOOL_NOT_ALLOWED",
                    document.deny_message,
                    manifest.manifest_id,
                    manifest.checksum,
                )
            if (
                operation not in tool.allowed_operations
                or operation not in tool_policy.allowed_operations
            ):
                return self._deny(
                    "OPERATION_NOT_ALLOWED",
                    document.deny_message,
                    manifest.manifest_id,
                    manifest.checksum,
                )
            operation_rule = tool_policy.operation_rules[operation]
            if not validate_parameters(operation_rule.parameter_schema, parameters):
                return self._deny(
                    "INVALID_PARAMETERS",
                    "Tool-call parameters do not match the registered policy schema",
                    manifest.manifest_id,
                    manifest.checksum,
                )
            if operation_rule.data_scope is not None:
                session_values = {
                    "customer_id": session.customer_id,
                    "user_id": session.user_id,
                }
                for scope_rule in operation_rule.data_scope.all:
                    session_value = session_values[scope_rule.session_claim]
                    parameter_value = parameters.get(scope_rule.parameter)
                    if not isinstance(parameter_value, str) or parameter_value != session_value:
                        return self._deny(
                            "DATA_SCOPE_VIOLATION",
                            document.deny_message,
                            manifest.manifest_id,
                            manifest.checksum,
                        )

            return PolicyDecision(
                allowed=True,
                reason_code="ALLOWED",
                message="Tool call is permitted",
                manifest_id=manifest.manifest_id,
                policy_checksum=manifest.checksum,
            )

    @staticmethod
    def _deny(
        code: str,
        message: str,
        manifest_id: str | None = None,
        checksum: str | None = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            allowed=False,
            reason_code=code,
            message=message,
            manifest_id=manifest_id,
            policy_checksum=checksum,
        )
