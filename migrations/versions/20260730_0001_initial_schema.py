"""Create the Phase 1 control-plane and synthetic CRM schema.

Revision ID: 20260730_0001
Revises:
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

agent_status = sa.Enum(
    "active",
    "suspended",
    "decommissioned",
    name="agent_status",
    native_enum=False,
    create_constraint=True,
)
tool_status = sa.Enum(
    "active",
    "disabled",
    name="tool_status",
    native_enum=False,
    create_constraint=True,
)
manifest_status = sa.Enum(
    "draft",
    "active",
    "superseded",
    "revoked",
    name="manifest_status",
    native_enum=False,
    create_constraint=True,
)
session_status = sa.Enum(
    "active",
    "expired",
    "revoked",
    name="session_status",
    native_enum=False,
    create_constraint=True,
)
audit_decision = sa.Enum(
    "allow",
    "block",
    "error",
    name="audit_decision",
    native_enum=False,
    create_constraint=True,
)
audit_execution_status = sa.Enum(
    "not_forwarded",
    "authorized",
    "executed",
    "tool_failed",
    "timed_out",
    name="audit_execution_status",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("oidc_subject", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("owning_team", sa.String(length=200), nullable=False),
        sa.Column("status", agent_status, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("agent_id"),
        sa.UniqueConstraint("oidc_subject"),
    )
    op.create_index("ix_agents_status", "agents", ["status"], unique=False)

    op.create_table(
        "tool_definitions",
        sa.Column("tool_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("adapter_type", sa.String(length=100), nullable=False),
        sa.Column("private_base_url", sa.String(length=500), nullable=False),
        sa.Column("allowed_operations", sa.JSON(), nullable=False),
        sa.Column("request_schema", sa.JSON(), nullable=False),
        sa.Column("response_schema", sa.JSON(), nullable=False),
        sa.Column("status", tool_status, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("tool_id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        "ix_tool_definitions_status",
        "tool_definitions",
        ["status"],
        unique=False,
    )

    op.create_table(
        "permission_manifests",
        sa.Column("manifest_id", sa.String(length=100), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", manifest_status, nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_from",
            name="ck_manifest_valid_window",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.agent_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("manifest_id"),
        sa.UniqueConstraint(
            "agent_id",
            "version",
            name="uq_manifest_agent_version",
        ),
    )
    op.create_index(
        "ix_permission_manifests_agent_id",
        "permission_manifests",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_permission_manifests_status",
        "permission_manifests",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_permission_manifests_active_agent",
        "permission_manifests",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "agent_sessions",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("token_jti", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("customer_id", sa.String(length=64), nullable=False),
        sa.Column("status", session_status, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_session_valid_window",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.agent_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("token_jti"),
    )
    op.create_index(
        "ix_agent_sessions_agent_id",
        "agent_sessions",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_sessions_customer_id",
        "agent_sessions",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_sessions_status",
        "agent_sessions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_agent_sessions_user_id",
        "agent_sessions",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "tool_call_audit_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("tool", sa.String(length=100), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("sanitized_parameters", sa.JSON(), nullable=False),
        sa.Column("decision", audit_decision, nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("matched_manifest_id", sa.String(length=100), nullable=True),
        sa.Column("policy_checksum", sa.String(length=64), nullable=True),
        sa.Column("execution_status", audit_execution_status, nullable=False),
        sa.Column("upstream_status_code", sa.Integer(), nullable=True),
        sa.Column("decision_latency_ms", sa.Integer(), nullable=True),
        sa.Column("total_latency_ms", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("previous_record_hash", sa.String(length=64), nullable=True),
        sa.Column("record_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.agent_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["matched_manifest_id"],
            ["permission_manifests.manifest_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.session_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint(
            "request_id",
            "sequence",
            name="uq_audit_request_sequence",
        ),
    )
    for column_name in (
        "agent_id",
        "decision",
        "execution_status",
        "operation",
        "reason_code",
        "request_id",
        "session_id",
        "timestamp",
        "tool",
        "trace_id",
        "user_id",
    ):
        op.create_index(
            f"ix_tool_call_audit_events_{column_name}",
            "tool_call_audit_events",
            [column_name],
            unique=False,
        )

    op.create_table(
        "crm_customers",
        sa.Column("customer_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("support_tier", sa.String(length=50), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("customer_id"),
    )


def downgrade() -> None:
    op.drop_table("crm_customers")

    for column_name in (
        "user_id",
        "trace_id",
        "tool",
        "timestamp",
        "session_id",
        "request_id",
        "reason_code",
        "operation",
        "execution_status",
        "decision",
        "agent_id",
    ):
        op.drop_index(
            f"ix_tool_call_audit_events_{column_name}",
            table_name="tool_call_audit_events",
        )
    op.drop_table("tool_call_audit_events")

    op.drop_index("ix_agent_sessions_user_id", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_status", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_customer_id", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_agent_id", table_name="agent_sessions")
    op.drop_table("agent_sessions")

    op.drop_index(
        "uq_permission_manifests_active_agent",
        table_name="permission_manifests",
    )
    op.drop_index(
        "ix_permission_manifests_status",
        table_name="permission_manifests",
    )
    op.drop_index(
        "ix_permission_manifests_agent_id",
        table_name="permission_manifests",
    )
    op.drop_table("permission_manifests")

    op.drop_index("ix_tool_definitions_status", table_name="tool_definitions")
    op.drop_table("tool_definitions")

    op.drop_index("ix_agents_status", table_name="agents")
    op.drop_table("agents")
