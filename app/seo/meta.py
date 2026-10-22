"""Шаблоны мета-тегов. Ручные значения из БД (title, description, h1) всегда важнее шаблона."""

import re
from dataclasses import dataclass

from starlette.requests import Request

from app.core.config import settings
from app.core.templating import format_rub

PRICE_TOKEN = "{price}"  # noqa: S105 — метка подстановки цены, не пароль


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


def city_prep() -> str:
    """«в Москве». Падеж задаётся в настройке CITY_PREPOSITIONAL."""
    return settings.city_prepositional


def city_dat() -> str:
    """«по Москве»."""
    return settings.city_prepositional
