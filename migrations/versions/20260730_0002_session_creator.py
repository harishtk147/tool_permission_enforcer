"""Record the trusted principal that creates each session.

Revision ID: 20260730_0002
Revises: 20260730_0001
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0002"
down_revision: str | None = "20260730_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_sessions",
        sa.Column(
            "created_by_subject",
            sa.String(length=255),
            server_default="migration:unknown",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_sessions", "created_by_subject")
