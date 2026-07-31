import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from services.permission_proxy.domain.enums import ManifestStatus
from services.permission_proxy.domain.exceptions import (
    EntityNotFoundError,
    InvalidManifestStateError,
)
from services.permission_proxy.domain.models import (
    Agent,
    AgentSession,
    PermissionManifest,
    ToolCallAuditEvent,
    ToolDefinition,
)


def manifest_checksum(document: dict[str, Any]) -> str:
    canonical = json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class AgentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, agent_id: str, *, for_update: bool = False) -> Agent | None:
        statement = select(Agent).where(Agent.agent_id == agent_id)
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def get_by_oidc_subject(self, oidc_subject: str) -> Agent | None:
        return self.session.scalar(select(Agent).where(Agent.oidc_subject == oidc_subject))

    def add(self, agent: Agent) -> Agent:
        self.session.add(agent)
        self.session.flush()
        return agent

    def count(self) -> int:
        return self.session.scalar(select(func.count()).select_from(Agent)) or 0


class ToolDefinitionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tool_id: str) -> ToolDefinition | None:
        return self.session.get(ToolDefinition, tool_id)

    def get_by_name(self, name: str) -> ToolDefinition | None:
        return self.session.scalar(select(ToolDefinition).where(ToolDefinition.name == name))

    def add(self, tool: ToolDefinition) -> ToolDefinition:
        self.session.add(tool)
        self.session.flush()
        return tool

    def count(self) -> int:
        return self.session.scalar(select(func.count()).select_from(ToolDefinition)) or 0


class ManifestRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, manifest_id: str, *, for_update: bool = False) -> PermissionManifest | None:
        statement = select(PermissionManifest).where(PermissionManifest.manifest_id == manifest_id)
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def get_active(self, agent_id: str) -> PermissionManifest | None:
        return self.session.scalar(
            select(PermissionManifest).where(
                PermissionManifest.agent_id == agent_id,
                PermissionManifest.status == ManifestStatus.ACTIVE,
            )
        )

    def add(self, manifest: PermissionManifest) -> PermissionManifest:
        self.session.add(manifest)
        self.session.flush()
        return manifest

    def activate(self, manifest_id: str, approved_by: str) -> PermissionManifest:
        target = self.get(manifest_id, for_update=True)
        if target is None:
            raise EntityNotFoundError(f"Manifest '{manifest_id}' does not exist")

        agent = AgentRepository(self.session).get(target.agent_id, for_update=True)
        if agent is None:
            raise EntityNotFoundError(f"Agent '{target.agent_id}' does not exist")

        if target.status == ManifestStatus.ACTIVE:
            return target
        if target.status != ManifestStatus.DRAFT:
            raise InvalidManifestStateError(
                f"Manifest '{manifest_id}' is '{target.status}' and cannot be activated"
            )

        current = self.get_active(target.agent_id)
        if current is not None and current.manifest_id != target.manifest_id:
            current.status = ManifestStatus.SUPERSEDED
            self.session.flush()

        target.status = ManifestStatus.ACTIVE
        target.approved_by = approved_by
        target.activated_at = datetime.now(UTC)
        self.session.flush()
        return target

    def count(self) -> int:
        return self.session.scalar(select(func.count()).select_from(PermissionManifest)) or 0


class SessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, session_id: str) -> AgentSession | None:
        return self.session.get(AgentSession, session_id)

    def get_by_jti(self, token_jti: str) -> AgentSession | None:
        return self.session.scalar(select(AgentSession).where(AgentSession.token_jti == token_jti))

    def add(self, agent_session: AgentSession) -> AgentSession:
        self.session.add(agent_session)
        self.session.flush()
        return agent_session

    def count(self) -> int:
        return self.session.scalar(select(func.count()).select_from(AgentSession)) or 0


class AuditEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, event: ToolCallAuditEvent) -> ToolCallAuditEvent:
        self.session.add(event)
        self.session.flush()
        return event

    def find_by_idempotency_key(
        self,
        agent_id: str,
        idempotency_key: str,
    ) -> ToolCallAuditEvent | None:
        return self.session.scalar(
            select(ToolCallAuditEvent)
            .where(
                ToolCallAuditEvent.agent_id == agent_id,
                ToolCallAuditEvent.idempotency_key == idempotency_key,
            )
            .order_by(ToolCallAuditEvent.timestamp, ToolCallAuditEvent.event_id)
            .limit(1)
        )

    def last_chain_event(self) -> ToolCallAuditEvent | None:
        return self.session.scalar(
            select(ToolCallAuditEvent)
            .order_by(
                ToolCallAuditEvent.timestamp.desc(),
                ToolCallAuditEvent.event_id.desc(),
            )
            .limit(1)
        )

    def list_events(
        self,
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
        tool: str | None = None,
        operation: str | None = None,
        decision: str | None = None,
        reason_code: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ToolCallAuditEvent]:
        statement: Select[tuple[ToolCallAuditEvent]] = select(ToolCallAuditEvent)
        filters = (
            (ToolCallAuditEvent.agent_id, agent_id),
            (ToolCallAuditEvent.session_id, session_id),
            (ToolCallAuditEvent.tool, tool),
            (ToolCallAuditEvent.operation, operation),
            (ToolCallAuditEvent.decision, decision),
            (ToolCallAuditEvent.reason_code, reason_code),
        )
        for column, value in filters:
            if value is not None:
                statement = statement.where(column == value)
        return list(
            self.session.scalars(
                statement.order_by(
                    ToolCallAuditEvent.timestamp.desc(),
                    ToolCallAuditEvent.event_id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        )

    def list_by_request(self, request_id: str) -> list[ToolCallAuditEvent]:
        return list(
            self.session.scalars(
                select(ToolCallAuditEvent)
                .where(ToolCallAuditEvent.request_id == request_id)
                .order_by(ToolCallAuditEvent.sequence)
            )
        )

    def all_chain_events(self) -> list[ToolCallAuditEvent]:
        return list(
            self.session.scalars(
                select(ToolCallAuditEvent).order_by(
                    ToolCallAuditEvent.timestamp,
                    ToolCallAuditEvent.event_id,
                )
            )
        )

    def count(self) -> int:
        return self.session.scalar(select(func.count()).select_from(ToolCallAuditEvent)) or 0
