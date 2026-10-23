"""Шаблоны получают модели чтения, а не записи из базы (правило «Модели чтения» в CLAUDE.md).

Запрос для страницы возвращает готовую структуру (dataclass) с тем, что страница показывает. ORM-объект
(`Product`, `Category`, `FilterLanding`, `Lead`, …) в шаблоне — это скрытые запросы к связям, шаблон, привязанный
к устройству базы, и связи, которые приходится грузить при любом запросе товара.

Тест перехватывает каждый вызов шаблона на страницах сайта и проходит по всему, что в него передано:
словари, списки, кортежи, dataclass-ы. Нашёлся ORM-объект — тест падает и показывает, где он лежит.
"""

import dataclasses

import httpx
import pytest
from sqlalchemy import select

from app.catalog.models import Product
from app.core.db import Base, SessionLocal
from app.core.templating import templates
from app.main import app as fastapi_app

PRODUCT = "armatura/12-mm/12-mm-a500s"
FETCH = {"X-Requested-With": "fetch"}


def orm_paths(value: object, path: str, seen: set[int]) -> list[str]:
    """Где в значении лежат ORM-объекты: «products.items[0] → Product»."""
    if isinstance(value, Base):
        return [f"{path} → {type(value).__name__}"]
    if id(value) in seen or isinstance(value, str | bytes | int | float | bool) or value is None:
        return []
    seen.add(id(value))
    if isinstance(value, dict):
        children = ((f"{path}.{k}", v) for k, v in value.items())
    elif isinstance(value, list | tuple | set | frozenset):
        children = ((f"{path}[{i}]", v) for i, v in enumerate(value))
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        children = ((f"{path}.{f.name}", getattr(value, f.name)) for f in dataclasses.fields(value))
    else:
        return []
    return [found for child_path, child in children for found in orm_paths(child, child_path, seen)]


@pytest.fixture
def rendered(monkeypatch):
    """Список (шаблон, где лежит ORM-объект) для каждого шаблона, отрисованного в тесте."""
    found: list[str] = []
    original = templates.TemplateResponse

    def spy(request, name, context=None, *args, **kwargs):
        ctx = {k: v for k, v in (context or {}).items() if k != "request"}
        found.extend(f"{name}: {p}" for p in orm_paths(ctx, "context", set()))
        return original(request, name, context, *args, **kwargs)

    monkeypatch.setattr(templates, "TemplateResponse", spy)
    return found


def site() -> httpx.AsyncClient:
    """Свой клиент на каждый тест: корзина живёт в cookie и не должна перетекать между тестами."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=fastapi_app), base_url="http://testserver")


async def product_id() -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(Product.id).where(Product.path == PRODUCT))


@pytest.mark.parametrize(
    "url",
    [
        "/",
        "/catalog/",
        "/catalog/armatura/",
        "/catalog/armatura/12-mm/",
        f"/catalog/{PRODUCT}/",
        "/search/?q=арматура",
        "/contacts/",
        "/delivery/",
        "/no-such-page/",
    ],
)
async def test_pages_render_without_orm_objects(rendered, url):
    async with site() as c:
        await c.get(url)
    assert rendered == []


async def test_calculator_partial_renders_without_orm_objects(rendered):
    async with site() as c:
        await c.get(f"/api/calc/{await product_id()}/", params={"unit": "m", "qty": "30"})
    assert rendered == []


async def test_cart_and_order_render_without_orm_objects(rendered):
    async with site() as c:
        await c.post("/cart/add/", data={"product_id": await product_id(), "unit": "pcs", "qty": "2"})
        await c.get("/cart/")
        await c.post("/cart/checkout/", data={"delivery": "pickup", "name": "Проверка", "phone": "+7 916 123-45-67"})
    assert rendered == []


async def test_lead_forms_render_without_orm_objects(rendered):
    pid = await product_id()
    form = {"product_id": pid, "unit": "pcs", "qty": "1", "phone": "8 916 123-45-67"}
    async with site() as c:
        await c.post("/api/lead/", data={**form, "phone": "123"}, headers=FETCH)  # ошибка: форма с товаром
        await c.post("/api/lead/", data=form, headers=FETCH)  # «Заявка принята» во всплывающем окне
        await c.post("/api/lead/", data=form)  # «Заявка принята» отдельной страницей
    assert rendered == []
