"""admin login failures for login limit

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-29 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Неудачные входы в админку: счёт общий для всех копий сайта (specs/003-admin-login-limit)
    op.create_table(
        "admin_login_failures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_hash", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_login_failures")),
    )
    op.create_index(
        "ix_admin_login_failures_client_hash_created_at", "admin_login_failures", ["client_hash", "created_at"]
    )
    op.create_index(op.f("ix_admin_login_failures_created_at"), "admin_login_failures", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_login_failures_created_at"), table_name="admin_login_failures")
    op.drop_index("ix_admin_login_failures_client_hash_created_at", table_name="admin_login_failures")
    op.drop_table("admin_login_failures")
