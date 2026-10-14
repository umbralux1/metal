"""Шаблоны мета-тегов. Ручные значения из БД (title, description, h1) всегда важнее шаблона."""

from dataclasses import dataclass

from starlette.requests import Request

from app.catalog.models import Category, FilterLanding, Product
from app.core.config import settings
from app.core.templating import format_rub


@dataclass
class PageMeta:
    title: str
    description: str
    h1: str
    canonical: str
    robots: str | None = None


def absolute(path: str) -> str:
    return settings.site_url.rstrip("/") + path


def robots_for(request: Request, indexable: bool = True) -> str | None:
    """noindex для служебных вариантов страницы: сортировки, фильтры, страницы пагинации 2+."""
    params = set(request.query_params.keys())
    page = request.query_params.get("page", "1")
    if not indexable or (params - {"page"}) or page != "1":
        return "noindex, follow"
    return None


def _from_price(min_kop: int | None) -> str:
    return f" по цене от {format_rub(min_kop)}" if min_kop else ""


def category_meta(request: Request, category: Category, min_kop: int | None) -> PageMeta:
    s = settings
    return PageMeta(
        title=category.title or f"{category.name} купить в {city_prep()} — цена за метр и тонну | {s.site_name}",
        description=category.description
        or f"{category.name} в наличии на складе{_from_price(min_kop)}. Доставка по {city_dat()} и области "
        f"в день заказа, резка в размер, продажа от 1 штуки. ☎ {s.phone}",
        h1=category.h1 or category.name,
        canonical=absolute(category.url),
        robots=robots_for(request),
    )


def landing_meta(request: Request, landing: FilterLanding, min_kop: int | None) -> PageMeta:
    s = settings
    return PageMeta(
        title=landing.title or f"{landing.name} купить в {city_prep()}{_from_price(min_kop)} с доставкой",
        description=landing.description
        or f"{landing.name}{_from_price(min_kop)}: ГОСТ, в наличии на складе. Доставка по {city_dat()} "
        f"и области, резка в размер. ☎ {s.phone}",
        h1=landing.h1 or landing.name,
        canonical=absolute(landing.url),
        robots=robots_for(request, indexable=landing.is_indexable),
    )


def product_meta(request: Request, product: Product) -> PageMeta:
    s = settings
    price = product.base_price
    price_part = f" — цена {format_rub(price.amount_kop)}/{price.unit.label}" if price else ""
    return PageMeta(
        title=product.title or f"{product.name}{price_part}, в наличии | {s.site_name}",
        description=product.description
        or f"{product.name}{price_part}. {'В наличии. ' if product.in_stock else ''}"
        f"Доставка по {city_dat()} и области, резка в размер. ☎ {s.phone}",
        h1=product.h1 or product.name,
        canonical=absolute(product.url),
        robots=robots_for(request),
    )


def city_prep() -> str:
    """«в Москве». Падеж задаётся в настройке CITY_PREPOSITIONAL."""
    return settings.city_prepositional


def city_dat() -> str:
    """«по Москве»."""
    return settings.city_prepositional
