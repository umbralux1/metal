from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Category, FilterLanding, Price, Product, Redirect

# Какие ключи FilterLanding.filters можно применять и к каким колонкам
FILTERABLE_COLUMNS = {
    "diameter_mm": Product.diameter_mm,
    "width_mm": Product.width_mm,
    "height_mm": Product.height_mm,
    "thickness_mm": Product.thickness_mm,
    "length_m": Product.length_m,
    "steel_grade": Product.steel_grade,
    "gost": Product.gost,
}
NUMERIC_KEYS = {"diameter_mm", "width_mm", "height_mm", "thickness_mm", "length_m"}


@dataclass
class ProductPage:
    items: list[Product]
    total: int
    page: int
    pages: int


def _coerce(key: str, value: Any) -> Any:
    return Decimal(str(value)) if key in NUMERIC_KEYS else value


def _apply_filters(stmt: Select, filters: dict[str, Any]) -> Select:
    for key, value in filters.items():
        column = FILTERABLE_COLUMNS.get(key)
        if column is None:
            raise ValueError(f"Неизвестный фильтр: {key}")
        if isinstance(value, list):
            stmt = stmt.where(column.in_([_coerce(key, v) for v in value]))
        else:
            stmt = stmt.where(column == _coerce(key, value))
    return stmt


def _in_category(category_path: str):
    """Товары раздела и всех его подразделов: по префиксу пути."""
    return Product.path.startswith(category_path + "/", autoescape=True)


async def get_category(session: AsyncSession, path: str) -> Category | None:
    stmt = select(Category).where(Category.path == path, Category.is_active.is_(True))
    return await session.scalar(stmt)


async def get_landing(session: AsyncSession, path: str) -> FilterLanding | None:
    return await session.scalar(select(FilterLanding).where(FilterLanding.path == path))


async def get_product(session: AsyncSession, path: str) -> Product | None:
    stmt = select(Product).where(Product.path == path, Product.is_active.is_(True))
    return await session.scalar(stmt)


async def get_redirect(session: AsyncSession, from_path: str) -> Redirect | None:
    return await session.scalar(select(Redirect).where(Redirect.from_path == from_path))


async def top_categories(session: AsyncSession) -> list[Category]:
    stmt = (
        select(Category)
        .where(Category.parent_id.is_(None), Category.is_active.is_(True))
        .order_by(Category.sort, Category.name)
    )
    return list(await session.scalars(stmt))


async def child_categories(session: AsyncSession, category: Category) -> list[Category]:
    stmt = (
        select(Category)
        .where(Category.parent_id == category.id, Category.is_active.is_(True))
        .order_by(Category.sort, Category.name)
    )
    return list(await session.scalars(stmt))


async def category_landings(session: AsyncSession, category: Category) -> list[FilterLanding]:
    """Посадочные раздела и его подразделов — для перелинковки «по размеру»."""
    stmt = (
        select(FilterLanding)
        .where(
            FilterLanding.is_indexable.is_(True),
            FilterLanding.path.startswith(category.path + "/", autoescape=True),
        )
        .order_by(FilterLanding.sort, FilterLanding.name)
    )
    return list(await session.scalars(stmt))


async def breadcrumb_categories(session: AsyncSession, path: str) -> list[Category]:
    """Разделы-предки по пути «a/b/c» → [a, a/b, a/b/c] (только существующие разделы)."""
    parts = path.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    rows = await session.scalars(select(Category).where(Category.path.in_(prefixes)))
    return sorted(rows, key=lambda c: len(c.path))


async def list_products(
    session: AsyncSession,
    category_path: str,
    filters: dict[str, Any] | None = None,
    page: int = 1,
    page_size: int = 24,
) -> ProductPage:
    base = select(Product).where(_in_category(category_path), Product.is_active.is_(True))
    base = _apply_filters(base, filters or {})

    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    pages = max(1, -(-total // page_size))
    stmt = base.order_by(Product.name).offset((page - 1) * page_size).limit(page_size)
    items = list(await session.scalars(stmt))
    return ProductPage(items=items, total=total, page=page, pages=pages)


async def min_price_kop(session: AsyncSession, category_path: str, filters: dict[str, Any] | None = None) -> int | None:
    """Минимальная цена в базовой единице товара — для «от N ₽» в title."""
    stmt = (
        select(func.min(Price.amount_kop))
        .join(Product, Price.product_id == Product.id)
        .where(_in_category(category_path), Product.is_active.is_(True), Price.unit == Product.base_unit)
    )
    stmt = _apply_filters(stmt, filters or {})
    return await session.scalar(stmt)
