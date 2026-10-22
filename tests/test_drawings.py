"""Чертёж сечения на странице товара: неполные размеры не роняют страницу.

Какой чертёж рисовать, можно задать вручную в админке («Доп. свойства», `{"profile": "tube_rect"}`). Если при этом
нужного размера нет (не заполнена толщина стенки, диаметр), страница товара отдавала 500. Теперь чертёж просто
не рисуется: без него страница полезна, без страницы — нет.
"""

from decimal import Decimal as D

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.catalog.drawings import section_svg
from app.catalog.models import Product
from app.core.db import SessionLocal

PIPE_PATH = "truba-profilnaya/kvadratnaya/40x40/40x40x2"


@pytest.mark.parametrize(
    ("profile", "sizes"),
    [
        ("tube_rect", {}),
        ("tube_rect", {"width_mm": D(40), "height_mm": D(40)}),  # нет толщины стенки
        ("rebar", {}),
        ("round", {}),
        ("plate", {}),
    ],
)
def test_no_drawing_when_sizes_missing(profile, sizes):
    product = Product(name="Товар", attrs={"profile": profile}, **sizes)
    assert section_svg(product) == ""


def test_drawing_with_full_sizes():
    product = Product(name="Труба 40×40×2", width_mm=D(40), height_mm=D(40), thickness_mm=D(2))
    assert "section-drawing" in section_svg(product)


@pytest_asyncio.fixture
async def pipe_without_thickness():
    """Как ошибка менеджера: чертёж трубы задан вручную, толщину стенки стёрли."""
    async with SessionLocal() as s:
        thickness_mm, attrs = (
            await s.execute(select(Product.thickness_mm, Product.attrs).where(Product.path == PIPE_PATH))
        ).one()
        await s.execute(
            update(Product).where(Product.path == PIPE_PATH).values(thickness_mm=None, attrs={"profile": "tube_rect"})
        )
        await s.commit()
    yield
    async with SessionLocal() as s:
        await s.execute(update(Product).where(Product.path == PIPE_PATH).values(thickness_mm=thickness_mm, attrs=attrs))
        await s.commit()


async def test_product_page_opens_without_drawing(client, pipe_without_thickness):
    r = await client.get(f"/catalog/{PIPE_PATH}/")
    assert r.status_code == 200
    assert "section-drawing" not in r.text
