"""Add idempotency keys to tool-call audit events.

Revision ID: 20260730_0003
Revises: 20260730_0002
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0003"
down_revision: str | None = "20260730_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_call_audit_events",
        sa.Column(
            "idempotency_key",
            sa.String(length=128),
            server_default="migration:unknown",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_tool_call_audit_events_idempotency_key",
        "tool_call_audit_events",
        ["idempotency_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tool_call_audit_events_idempotency_key",
        table_name="tool_call_audit_events",
    )
    op.drop_column("tool_call_audit_events", "idempotency_key")
