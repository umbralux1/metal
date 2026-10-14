"""Все модели в одном месте: импортируется Alembic'ом и тестами."""

from app.catalog.models import Category, FilterLanding, Price, Product, Redirect, Unit  # noqa: F401
from app.core.db import Base  # noqa: F401
from app.leads.models import Lead  # noqa: F401
