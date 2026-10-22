"""SEO страниц каталога: мета-теги раздела, страницы размера и товара, разметка товаров schema.org.

Общие помощники (PageMeta, absolute, robots_for, with_price, разметка организации и крошек) — в app/seo:
он не знает про каталог, каталог пользуется им.
"""

from typing import Any

from starlette.requests import Request

from app.catalog.landing_rules import display_name
from app.catalog.models import Category, FilterLanding, Product, Unit
from app.core.config import settings
from app.core.templating import format_rub
from app.seo.meta import PageMeta, absolute, city_dat, city_prep, robots_for, with_price


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


def item_list_jsonld(products: list[Product]) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "url": absolute(p.url), "name": p.name}
            for i, p in enumerate(products, start=1)
        ],
    }


def product_jsonld(item: Product) -> dict[str, Any]:
    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": item.name,
        "url": absolute(item.url),
        "category": item.category.name if item.category else None,
    }
    if item.sku:
        data["sku"] = item.sku
    price = item.base_price
    if price:
        data["offers"] = {
            "@type": "Offer",
            "price": f"{price.amount_kop / 100:.2f}",
            "priceCurrency": "RUB",
            "availability": "https://schema.org/InStock" if item.in_stock else "https://schema.org/OutOfStock",
            "url": absolute(item.url),
            "seller": {"@type": "Organization", "name": settings.site_name},
        }
    return {k: v for k, v in data.items() if v is not None}
