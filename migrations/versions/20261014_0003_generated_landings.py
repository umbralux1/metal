"""generated landings

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "filter_landings",
        sa.Column("is_generated", sa.Boolean(), server_default="false", nullable=False),
    )
    # Посадочные из демо-данных без своих текстов отдаём генератору: он заполнит тексты,
    # а размеры с одним товаром закроет от индекса. Посадочные с ручными текстами остаются ручными.
    op.execute(
        "UPDATE filter_landings SET is_generated = true "
        "WHERE title IS NULL AND description IS NULL AND h1 IS NULL AND seo_text IS NULL "
        "AND is_indexable"
    )


def downgrade() -> None:
    op.drop_column("filter_landings", "is_generated")
