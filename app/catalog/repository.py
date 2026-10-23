import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, joinedload, selectinload

from app.catalog.models import Category, FilterLanding, Price, Product, Redirect
from app.catalog.utils import normalize_search

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

# Связи моделей не грузятся сами (lazy="raise", tests/test_relations.py) — нужное загружаем в запросе явно
PRODUCT_CARD = (joinedload(Product.category), selectinload(Product.prices))  # страница, строка, расчёт цены
LANDING_WITH_CATEGORY = joinedload(FilterLanding.category)


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


def visible_category(category: type[Category] = Category) -> ColumnElement[bool]:
    """Раздел виден, если включены он сам и все разделы выше: выключенный раздел прячет всё, что внутри."""
    hidden = aliased(Category)
    return ~exists().where(
        hidden.is_active.is_(False),
        or_(category.path == hidden.path, category.path.startswith(hidden.path.concat("/"))),
    )


def visible_product() -> ColumnElement[bool]:
    """Товар виден, если включён он сам и его раздел виден."""
    return Product.is_active.is_(True) & Product.category_id.in_(select(Category.id).where(visible_category()))


def visible_landing() -> ColumnElement[bool]:
    """Страница размера видна, если виден её раздел."""
    return FilterLanding.category_id.in_(select(Category.id).where(visible_category()))


def _in_category(category_path: str):
    """Товары раздела и всех его подразделов — по разделу товара, а не по адресу.

    Адрес товара может лежать в посадочной размера выше своего раздела
    (armatura/12-mm/12-mm-a500s при разделе armatura/a500c), поэтому префикс пути здесь не подходит.
    """
    subtree = select(Category.id).where(
        or_(Category.path == category_path, Category.path.startswith(category_path + "/", autoescape=True))
    )
    return Product.category_id.in_(subtree)


async def get_category(session: AsyncSession, path: str) -> Category | None:
    return await session.scalar(select(Category).where(Category.path == path, visible_category()))


async def get_landing(session: AsyncSession, path: str) -> FilterLanding | None:
    stmt = select(FilterLanding).where(FilterLanding.path == path, visible_landing()).options(LANDING_WITH_CATEGORY)
    return await session.scalar(stmt)


async def get_product(session: AsyncSession, path: str) -> Product | None:
    return await session.scalar(select(Product).where(Product.path == path, visible_product()).options(*PRODUCT_CARD))


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
            visible_landing(),
        )
        .order_by(FilterLanding.sort, FilterLanding.name)
    )
    return list(await session.scalars(stmt))


async def breadcrumb_nodes(session: AsyncSession, path: str) -> list[Category | FilterLanding]:
    """Предки по адресу: разделы и посадочные размера (у товара внутри посадочной она тоже в крошках)."""
    parts = path.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    categories = list(await session.scalars(select(Category).where(Category.path.in_(prefixes))))
    landings = list(await session.scalars(select(FilterLanding).where(FilterLanding.path.in_(prefixes))))
    return sorted([*categories, *landings], key=lambda node: len(node.path))


async def size_landing(session: AsyncSession, product: Product) -> FilterLanding | None:
    """Посадочная размера, внутри которой лежит товар (адрес товара = её адрес + slug)."""
    parent = product.path.rsplit("/", 1)[0]
    return await session.scalar(
        select(FilterLanding).where(FilterLanding.path == parent).options(LANDING_WITH_CATEGORY)
    )


async def same_size_products(session: AsyncSession, landing: FilterLanding, exclude: Product) -> list[Product]:
    """Другие толщины / марки того же размера — товары внутри той же посадочной."""
    stmt = (
        select(Product)
        .where(
            Product.path.startswith(landing.path + "/", autoescape=True),
            visible_product(),
            Product.id != exclude.id,
        )
        .order_by(Product.thickness_mm, Product.name)
        .options(*PRODUCT_CARD)
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
    base = select(Product).where(_in_category(category_path), visible_product())
    base = _apply_filters(base, filters or {})

    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    pages = max(1, -(-total // page_size))
    stmt = base.order_by(Product.name).offset((page - 1) * page_size).limit(page_size).options(*PRODUCT_CARD)
    items = list(await session.scalars(stmt))
    return ProductPage(items=items, total=total, page=page, pages=pages)


async def min_price_kop(session: AsyncSession, category_path: str, filters: dict[str, Any] | None = None) -> int | None:
    """Минимальная цена в базовой единице товара — для «от N ₽» в title."""
    stmt = (
        select(func.min(Price.amount_kop))
        .join(Product, Price.product_id == Product.id)
        .where(_in_category(category_path), visible_product(), Price.unit == Product.base_unit)
    )
    stmt = _apply_filters(stmt, filters or {})
    return await session.scalar(stmt)


def _token_filter(column, token: str, prefix: bool):
    """Слово — по подстроке («армат» → «арматура»). Число — только с начала числа, чтобы «50» не находилось
    внутри «ГОСТ 8509-93»; целиком, если prefix=False (12 ≠ 120), или началом, если пользователь ещё печатает."""
    if not any(ch.isdigit() for ch in token):
        return column.contains(token, autoescape=True)
    tail = "" if prefix else "([^0-9]|$)"
    return column.op("~")(f"(^|[^0-9]){re.escape(token)}{tail}")


async def search_products(
    session: AsyncSession, query: str, limit: int = 60, prefix_last: bool = False
) -> list[Product]:
    """Все слова запроса должны встретиться в search_text; сверху — самые похожие (pg_trgm).

    prefix_last — последнее слово может быть недописанным (автодополнение: «40х2» → «40х20»).
    """
    norm = normalize_search(query)
    tokens = norm.split()[:6]
    if not tokens:
        return []
    stmt = select(Product).where(visible_product())
    for i, token in enumerate(tokens):
        stmt = stmt.where(_token_filter(Product.search_text, token, prefix_last and i == len(tokens) - 1))
    stmt = stmt.order_by(func.similarity(Product.search_text, norm).desc(), Product.name).limit(limit)
    stmt = stmt.options(*PRODUCT_CARD)
    return list(await session.scalars(stmt))


@dataclass
class Suggestion:
    kind: str  # category | landing | product
    name: str
    url: str
    meta: str = ""


async def suggest(session: AsyncSession, query: str, limit_products: int = 6) -> list[Suggestion]:
    """Подсказки под строкой поиска: разделы, посадочные размеров и товары (те же правила, что у поиска)."""
    from app.core.templating import format_rub

    norm = normalize_search(query)
    tokens = norm.split()[:6]
    if not tokens:
        return []
    words = [t for t in tokens if not any(ch.isdigit() for ch in t)]
    items: list[Suggestion] = []

    if words and len(words) == len(tokens):
        cats = select(Category).where(visible_category())
        for word in words:
            cats = cats.where(func.lower(Category.name).contains(word, autoescape=True))
        for c in await session.scalars(cats.order_by(func.length(Category.path), Category.sort).limit(3)):
            items.append(Suggestion("category", c.name, c.url, "Раздел"))

    # В названиях посадочных размер записан кириллической «х»: «Труба профильная 40х20»
    landing_text = func.regexp_replace(func.lower(FilterLanding.name), r"(\d)\s*[хx×]\s*(\d)", r"\1x\2", "g")
    landings = select(FilterLanding).where(FilterLanding.is_indexable.is_(True), visible_landing())
    for i, token in enumerate(tokens):
        landings = landings.where(_token_filter(landing_text, token, prefix=i == len(tokens) - 1))
    for item in await session.scalars(landings.order_by(FilterLanding.sort, FilterLanding.name).limit(3)):
        items.append(Suggestion("landing", item.name, item.url, "Все размеры"))

    for p in await search_products(session, query, limit=limit_products, prefix_last=True):
        price = p.base_price
        meta = f"{format_rub(price.amount_kop)}/{price.unit.label}" if price else "Цена по запросу"
        items.append(Suggestion("product", p.name, p.url, meta))
    return items


async def get_product_by_id(session: AsyncSession, product_id: int) -> Product | None:
    """Товар с ценами и разделом — для расчёта калькулятора, корзины и заявки."""
    return await session.scalar(select(Product).where(Product.id == product_id).options(*PRODUCT_CARD))


async def inactive_parent_url(session: AsyncSession, path: str) -> str | None:
    """Скрытый товар, раздел или страница размера (сам выключен или выключен раздел выше): куда перенаправить —
    ближайший видимый раздел выше или каталог. Адреса нет вовсе — None (будет 404)."""
    exists_hidden = (
        await session.scalar(select(Product.id).where(Product.path == path, ~visible_product()))
        or await session.scalar(select(Category.id).where(Category.path == path, ~visible_category()))
        or await session.scalar(select(FilterLanding.id).where(FilterLanding.path == path, ~visible_landing()))
    )
    if not exists_hidden:
        return None
    parts = path.split("/")[:-1]
    while parts:
        candidate = "/".join(parts)
        if await session.scalar(select(Category.id).where(Category.path == candidate, visible_category())):
            return f"/catalog/{candidate}/"
        parts.pop()
    return "/catalog/"
