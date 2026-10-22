"""N+1: число запросов к базе на странице не зависит от числа товаров на ней."""

from decimal import Decimal

import pytest_asyncio
from sqlalchemy import delete, select

from app.catalog.models import Category, Price, Product, Unit
from app.core.db import SessionLocal
from tests.helpers import count_queries

PATH = "test-n-plus-one"


async def add_products(category_id: int, start: int, count: int) -> None:
    async with SessionLocal() as session:
        for i in range(start, start + count):
            product = Product(
                category_id=category_id,
                slug=f"p{i}",
                path=f"{PATH}/p{i}",
                name=f"Тестовый прокат {i}",
                diameter_mm=Decimal(i),
                length_m=Decimal(6),
                weight_per_m_kg=Decimal("0.888"),
            )
            product.prices = [Price(unit=Unit.METER, amount_kop=4000 + i), Price(unit=Unit.TON, amount_kop=4_800_000)]
            session.add(product)
        await session.commit()


@pytest_asyncio.fixture
async def category():
    async with SessionLocal() as session:
        cat = Category(slug=PATH, path=PATH, name="Тест N+1", sort=999)
        session.add(cat)
        await session.commit()
        yield cat
        product_ids = select(Product.id).where(Product.category_id == cat.id)
        await session.execute(delete(Price).where(Price.product_id.in_(product_ids)))
        await session.execute(delete(Product).where(Product.category_id == cat.id))
        await session.execute(delete(Category).where(Category.id == cat.id))
        await session.commit()


async def queries_on(client, url: str) -> int:
    await client.get(url)  # прогрев: меню каталога кэшируется на минуту
    with count_queries() as queries:
        r = await client.get(url)
    assert r.status_code == 200, url
    return len(queries)


async def test_category_page_queries_do_not_grow_with_products(client, category):
    await add_products(category.id, 1, 2)
    few = await queries_on(client, f"/catalog/{PATH}/")
    await add_products(category.id, 3, 10)
    many = await queries_on(client, f"/catalog/{PATH}/")
    assert many == few, f"2 товара — {few} запросов, 12 товаров — {many}: похоже на N+1"


async def test_home_page_queries_do_not_grow_with_products(client, category):
    await add_products(category.id, 1, 2)
    few = await queries_on(client, "/")
    await add_products(category.id, 3, 10)
    many = await queries_on(client, "/")
    assert many == few, f"главная: {few} запросов → {many} после добавления товаров"
