"""delivery vehicles

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-21 15:19:03.861020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Машины доставки и тарифы. Начальные тарифы кладёт app/delivery/seed.py при запуске сервера.
    op.create_table(
        "delivery_vehicles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("max_weight_kg", sa.Integer(), nullable=False),
        sa.Column("max_length_m", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("base_price_kop", sa.Integer(), nullable=False),
        sa.Column("included_km", sa.Integer(), nullable=False),
        sa.Column("price_per_km_kop", sa.Integer(), nullable=False),
        sa.Column("self_unloading", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("base_price_kop >= 0", name=op.f("ck_delivery_vehicles_base_price_not_negative")),
        sa.CheckConstraint("included_km >= 0", name=op.f("ck_delivery_vehicles_included_km_not_negative")),
        sa.CheckConstraint("max_length_m > 0", name=op.f("ck_delivery_vehicles_max_length_positive")),
        sa.CheckConstraint("max_weight_kg > 0", name=op.f("ck_delivery_vehicles_max_weight_positive")),
        sa.CheckConstraint("price_per_km_kop >= 0", name=op.f("ck_delivery_vehicles_price_per_km_not_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery_vehicles")),
        sa.UniqueConstraint("name", name=op.f("uq_delivery_vehicles_name")),
    )


def downgrade() -> None:
    op.drop_table("delivery_vehicles")
