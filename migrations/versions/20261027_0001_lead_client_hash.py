"""lead client fingerprint for rate limit

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-27 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Отпечаток адреса подключения для счёта заявок (specs/001-lead-rate-limit); у старых заявок — пусто
    op.add_column("leads", sa.Column("client_hash", sa.String(length=32), nullable=True))
    op.create_index("ix_leads_client_hash_created_at", "leads", ["client_hash", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_leads_client_hash_created_at", table_name="leads")
    op.drop_column("leads", "client_hash")
