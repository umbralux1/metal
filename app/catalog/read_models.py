"""Модели чтения каталога: что страница показывает, без связи с базой.

Шаблоны получают только эти структуры, а не ORM-объекты (`tests/test_read_models.py`): так шаблон не может
выполнить скрытый запрос и не зависит от устройства таблиц. Собираются из уже загруженных записей функциями
ниже; запросы к базе — в `repository.py`.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from markupsafe import Markup

from app.catalog.drawings import section_svg
from app.catalog.models import Category, FilterLanding, Product, Unit


@dataclass(frozen=True)
class PriceView:
    unit: Unit
    amount_kop: int


@dataclass(frozen=True)
class NodeLink:
    """Ссылка на раздел или страницу размера: меню, «По размеру», «Другие размеры», главная."""

    name: str
    url: str


@dataclass(frozen=True)
class SizeLink(NodeLink):
    """Страница размера, внутри которой лежит товар: ссылка «Все товары» — только если она в индексе."""

    is_indexable: bool = True


@dataclass(frozen=True)
class NodeView:
    """Раздел или страница размера, которую показывает страница списка."""

    name: str
    url: str
    seo_text: str | None


@dataclass(frozen=True)
class ProductLink:
    """Товар как ссылка: корзина, форма заявки, «Заявка принята»."""

    id: int
    name: str
    url: str
    path: str


@dataclass(frozen=True)
class ProductRow(ProductLink):
    """Строка таблицы товаров: раздел, страница размера, поиск, другие варианты того же размера."""

    size_label: str = ""
    steel_grade: str | None = None
    gost: str | None = None
    thickness_mm: Decimal | None = None
    weight_per_m_kg: Decimal | None = None
    base_unit: Unit = Unit.METER
    base_price: PriceView | None = None
    prices: tuple[PriceView, ...] = ()


@dataclass(frozen=True)
class ProductCard(ProductRow):
    """Карточка товара: всё, что показывает страница товара и калькулятор."""

    in_stock: bool = True
    length_m: Decimal | None = None
    sku: str | None = None
    seo_text: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)
    drawing: Markup = Markup("")


@dataclass(frozen=True)
class RowPage:
    """Страница списка товаров с пагинацией."""

    items: list[ProductRow]
    total: int
    page: int
    pages: int


def node_link(node: Category | FilterLanding) -> NodeLink:
    return NodeLink(name=node.name, url=node.url)


def size_link(landing: FilterLanding) -> SizeLink:
    return SizeLink(name=landing.name, url=landing.url, is_indexable=landing.is_indexable)


def node_view(node: Category | FilterLanding) -> NodeView:
    return NodeView(name=node.name, url=node.url, seo_text=node.seo_text)


def product_link(product: Product) -> ProductLink:
    return ProductLink(id=product.id, name=product.name, url=product.url, path=product.path)


def _price(price: Any) -> PriceView | None:
    return PriceView(unit=price.unit, amount_kop=price.amount_kop) if price else None


def _row_fields(product: Product) -> dict[str, Any]:
    return {
        "id": product.id,
        "name": product.name,
        "url": product.url,
        "path": product.path,
        "size_label": product.size_label,
        "steel_grade": product.steel_grade,
        "gost": product.gost,
        "thickness_mm": product.thickness_mm,
        "weight_per_m_kg": product.weight_per_m_kg,
        "base_unit": product.base_unit,
        "base_price": _price(product.base_price),
        "prices": tuple(PriceView(unit=p.unit, amount_kop=p.amount_kop) for p in product.prices),
    }


def product_row(product: Product) -> ProductRow:
    return ProductRow(**_row_fields(product))


def product_card(product: Product) -> ProductCard:
    return ProductCard(
        **_row_fields(product),
        in_stock=product.in_stock,
        length_m=product.length_m,
        sku=product.sku,
        seo_text=product.seo_text,
        attrs=dict(product.attrs or {}),
        drawing=section_svg(product),
    )


def row_page(items: list[Product], total: int, page: int, pages: int) -> RowPage:
    return RowPage(items=[product_row(p) for p in items], total=total, page=page, pages=pages)
