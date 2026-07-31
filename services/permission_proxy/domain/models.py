from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from services.common.database import Base
from services.permission_proxy.domain.enums import (
    AgentStatus,
    AuditDecision,
    AuditExecutionStatus,
    ManifestStatus,
    SessionStatus,
    ToolStatus,
)


def enum_values(enum_type: type[Any]) -> list[str]:
    return [member.value for member in enum_type]


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Agent(TimestampMixin, Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    oidc_subject: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owning_team: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(
            AgentStatus,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=True,
            name="agent_status",
        ),
        default=AgentStatus.ACTIVE,
        nullable=False,
        index=True,
    )

    manifests: Mapped[list["PermissionManifest"]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    sessions: Mapped[list["AgentSession"]] = relationship(back_populates="agent")


class ToolDefinition(TimestampMixin, Base):
    __tablename__ = "tool_definitions"

    tool_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(100), nullable=False)
    private_base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    allowed_operations: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    request_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    response_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[ToolStatus] = mapped_column(
        Enum(
            ToolStatus,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=True,
            name="tool_status",
        ),
        default=ToolStatus.ACTIVE,
        nullable=False,
        index=True,
    )


class PermissionManifest(Base):
    __tablename__ = "permission_manifests"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_manifest_agent_version"),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_from",
            name="ck_manifest_valid_window",
        ),
        Index(
            "uq_permission_manifests_active_agent",
            "agent_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    manifest_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ManifestStatus] = mapped_column(
        Enum(
            ManifestStatus,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=True,
            name="manifest_status",
        ),
        default=ManifestStatus.DRAFT,
        nullable=False,
        index=True,
    )
    document: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(255))
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent: Mapped[Agent] = relationship(back_populates="manifests")


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (CheckConstraint("expires_at > created_at", name="ck_session_valid_window"),)

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_jti: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.agent_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by_subject: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default="migration:unknown",
    )
    status: Mapped[SessionStatus] = mapped_column(
        Enum(
            SessionStatus,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=True,
            name="session_status",
        ),
        default=SessionStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent: Mapped[Agent] = relationship(back_populates="sessions")


class ToolCallAuditEvent(Base):
    __tablename__ = "tool_call_audit_events"
    __table_args__ = (UniqueConstraint("request_id", "sequence", name="uq_audit_request_sequence"),)

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.agent_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_sessions.session_id", ondelete="RESTRICT"),
        index=True,
    )
    user_id: Mapped[str | None] = mapped_column(String(128), index=True)
    tool: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    sanitized_parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    decision: Mapped[AuditDecision] = mapped_column(
        Enum(
            AuditDecision,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=True,
            name="audit_decision",
        ),
        nullable=False,
        index=True,
    )
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    matched_manifest_id: Mapped[str | None] = mapped_column(
        ForeignKey("permission_manifests.manifest_id", ondelete="RESTRICT")
    )
    policy_checksum: Mapped[str | None] = mapped_column(String(64))
    execution_status: Mapped[AuditExecutionStatus] = mapped_column(
        Enum(
            AuditExecutionStatus,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=True,
            name="audit_execution_status",
        ),
        nullable=False,
        index=True,
    )
    upstream_status_code: Mapped[int | None] = mapped_column(Integer)
    decision_latency_ms: Mapped[int | None] = mapped_column(Integer)
    total_latency_ms: Mapped[int | None] = mapped_column(Integer)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    previous_record_hash: Mapped[str | None] = mapped_column(String(64))
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
