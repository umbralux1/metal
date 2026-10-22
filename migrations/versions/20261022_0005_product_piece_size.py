"""product piece weight and length

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Вес и длина одной штуки — для подбора машины доставки (листы, профнастил, сваи)
    op.add_column("products", sa.Column("weight_per_piece_kg", sa.Numeric(precision=10, scale=3), nullable=True))
    op.add_column("products", sa.Column("piece_length_m", sa.Numeric(precision=6, scale=3), nullable=True))
    op.create_check_constraint(op.f("ck_products_weight_per_piece_positive"), "products", "weight_per_piece_kg > 0")
    op.create_check_constraint(op.f("ck_products_piece_length_positive"), "products", "piece_length_m > 0")
    # Уже заведённые листы и сваи: вес и размер были только в attrs — переносим в колонки.
    # CASE с регуляркой: мусор в attrs не уронит миграцию на приведении типа (порядок в AND не гарантирован),
    # а ограничение числа цифр — на переполнении колонки
    op.execute(
        """
        UPDATE products SET weight_per_piece_kg = (attrs->>'sheet_kg')::numeric
        WHERE CASE WHEN attrs->>'sheet_kg' ~ '^[0-9]{1,7}(\\.[0-9]+)?$' THEN (attrs->>'sheet_kg')::numeric END > 0
        """
    )
    op.execute(
        """
        UPDATE products SET piece_length_m = GREATEST(
            split_part(attrs->>'format', '×', 1)::numeric, split_part(attrs->>'format', '×', 2)::numeric
        ) / 1000
        WHERE attrs->>'format' ~ '^[0-9]{1,5}×[0-9]{1,5}$'
        """
    )
    op.execute(
        """
        UPDATE products SET piece_length_m = (attrs->>'length_mm')::numeric / 1000
        WHERE CASE WHEN attrs->>'length_mm' ~ '^[0-9]{1,5}$' THEN (attrs->>'length_mm')::numeric END > 0
        """
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_products_piece_length_positive"), "products", type_="check")
    op.drop_constraint(op.f("ck_products_weight_per_piece_positive"), "products", type_="check")
    op.drop_column("products", "piece_length_m")
    op.drop_column("products", "weight_per_piece_kg")
