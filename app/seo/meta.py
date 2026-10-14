"""Шаблоны мета-тегов. Ручные значения из БД (title, description, h1) всегда важнее шаблона."""

import re
from dataclasses import dataclass

from starlette.requests import Request

from app.catalog.landing_rules import display_name
from app.catalog.models import Category, FilterLanding, Product, Unit
from app.core.config import settings
from app.core.templating import format_rub

PRICE_TOKEN = "{price}"


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


def with_price(text: str, min_kop: int | None) -> str:
    """{price} в ручных и сгенерированных текстах → «от 43,25 ₽»; цены нет — токен убирается."""
    if PRICE_TOKEN not in text:
        return text
    if min_kop:
        return text.replace(PRICE_TOKEN, f"от {format_rub(min_kop)}")
    return re.sub(r"\s*\{price\}", "", text)


def _from_price(min_kop: int | None) -> str:
    return f" по цене от {format_rub(min_kop)}" if min_kop else ""


def category_meta(request: Request, category: Category, min_kop: int | None) -> PageMeta:
    s = settings
    return PageMeta(
        title=with_price(category.title, min_kop)
        if category.title
        else f"{category.name} купить в {city_prep()} — цена за метр и тонну | {s.site_name}",
        description=with_price(category.description, min_kop)
        if category.description
        else f"{category.name} в наличии на складе{_from_price(min_kop)}. Доставка по {city_dat()} и области, "
        f"резка в размер, продажа от 1 штуки. ☎ {s.phone}",
        h1=category.h1 or category.name,
        canonical=absolute(category.url),
        robots=robots_for(request),
    )


def landing_meta(request: Request, landing: FilterLanding, min_kop: int | None) -> PageMeta:
    s = settings
    return PageMeta(
        title=with_price(landing.title, min_kop)
        if landing.title
        else f"{landing.name} купить в {city_prep()}{_from_price(min_kop)} с доставкой",
        description=with_price(landing.description, min_kop)
        if landing.description
        else f"{landing.name}{_from_price(min_kop)}: ГОСТ, в наличии на складе. Доставка по {city_dat()} "
        f"и области, резка в размер. ☎ {s.phone}",
        h1=landing.h1 or landing.name,
        canonical=absolute(landing.url),
        robots=robots_for(request, indexable=landing.is_indexable),
    )


def piece_price_kop(product: Product) -> int | None:
    """Цена одной штуки стандартной длины: цена метра × длина (труба 6 м, пруток 11,7 м)."""
    meter = product.price_for(Unit.METER)
    if meter and product.length_m:
        return round(meter.amount_kop * float(product.length_m))
    return None


def product_meta(request: Request, product: Product) -> PageMeta:
    """«Труба профильная квадратная 20х20х2 купить в Москве — цена 98 ₽/м»: товар, синоним раздела,
    «купить», город и цена за единицу — в той форме, в какой это ищут."""
    s = settings
    category_path = product.category.path if product.category else ""
    shown = display_name(product.name, category_path)
    price = product.base_price
    price_part = f" — цена {format_rub(price.amount_kop)}/{price.unit.label}" if price else ""
    title = f"{shown} купить в {city_prep()}{price_part}"
    if len(title) > 75:
        title = f"{product.name} купить в {city_prep()}{price_part}"

    offers = []
    for pr in sorted(product.prices, key=lambda x: x.unit != product.base_unit):
        offers.append(f"{format_rub(pr.amount_kop)}/{pr.unit.label}")
    piece = piece_price_kop(product)
    if piece:
        offers.append(f"{num_ru(product.length_m)} м — {format_rub(piece)}")
    stock = "В наличии на складе" if product.in_stock else "Под заказ"
    description = (
        f"{shown}: {', '.join(offers)}. {stock}. " if offers else f"{shown}. {stock}. "
    ) + f"Продаём от 1 шт., режем в размер, доставка по {city_dat()} и области. ☎ {s.phone}"
    return PageMeta(
        title=with_price(product.title, price.amount_kop if price else None) if product.title else title,
        description=product.description or description,
        h1=product.h1 or product.name,
        canonical=absolute(product.url),
        robots=robots_for(request),
    )


def num_ru(value) -> str:
    """6.000 → «6», 11.700 → «11,7»."""
    from decimal import Decimal

    return format(Decimal(str(value)).normalize(), "f").replace(".", ",")


def city_prep() -> str:
    """«в Москве». Падеж задаётся в настройке CITY_PREPOSITIONAL."""
    return settings.city_prepositional


def city_dat() -> str:
    """«по Москве»."""
    return settings.city_prepositional
