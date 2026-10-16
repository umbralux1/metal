"""Микроразметка schema.org в JSON-LD."""

import json
from typing import Any

from app.catalog.models import Product
from app.core.config import settings
from app.seo.hours import opening_hours
from app.seo.meta import absolute


def to_script(data: dict[str, Any]) -> str:
    """JSON для <script type="application/ld+json">, безопасный от закрытия тега."""
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def organization() -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": settings.site_name,
        "url": absolute("/"),
        "telephone": settings.phone,
        "email": settings.email,
    }


def local_business() -> dict[str, Any]:
    """Склад-магазин для страницы контактов: адрес, часы работы, координаты (если заданы)."""
    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Store",
        "name": settings.site_name,
        "url": absolute("/"),
        "telephone": settings.phone,
        "email": settings.email,
        "address": {
            "@type": "PostalAddress",
            "addressLocality": settings.city,
            "addressCountry": "RU",
            **({"streetAddress": settings.address} if settings.address else {}),
        },
    }
    # Часы из того же текста, что на странице: по ним поиск пишет «открыто до 19:00»
    if hours := opening_hours(settings.work_hours):
        data["openingHoursSpecification"] = hours
    if settings.map_lat is not None and settings.map_lon is not None:
        data["geo"] = {"@type": "GeoCoordinates", "latitude": settings.map_lat, "longitude": settings.map_lon}
    return data


def breadcrumbs(items: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name, "item": absolute(url)}
            for i, (name, url) in enumerate(items, start=1)
        ],
    }


def item_list(products: list[Product]) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "url": absolute(p.url), "name": p.name}
            for i, p in enumerate(products, start=1)
        ],
    }


def product(item: Product) -> dict[str, Any]:
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
