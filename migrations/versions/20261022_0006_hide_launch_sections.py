"""hide sections not sold at launch

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Скрыты на запуске (22.10.2026), вернуть позже — галочкой «Активен» в админке. Подразделы и товары не трогаем:
# выключенный раздел прячет всё, что внутри (app/catalog/repository.py, visible_category). Копия списка из
# app/catalog/demo_catalog.HIDDEN_AT_LAUNCH — миграция не должна зависеть от кода приложения.
HIDDEN = ("shtaketnik", "zabory", "krepezh", "fitingi", "stroymaterialy", "petli", "profnastil", "zaglushki")


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE categories SET is_active = false WHERE path IN :paths").bindparams(
            sa.bindparam("paths", HIDDEN, expanding=True)
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE categories SET is_active = true WHERE path IN :paths").bindparams(
            sa.bindparam("paths", HIDDEN, expanding=True)
        )
    )
