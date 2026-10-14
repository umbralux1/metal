"""Демо-данные для разработки и тестов. Цены условные.

Запуск: python -m app.catalog.seed
"""

import asyncio
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.landings import generate_landings
from app.catalog.models import Category, FilterLanding, Price, Product, Unit
from app.catalog.utils import normalize_search, slugify
from app.core.db import SessionLocal, engine

D = Decimal


def _category(slug: str, name: str, parent: Category | None = None, **kw) -> Category:
    path = f"{parent.path}/{slug}" if parent else slug
    return Category(slug=slug, path=path, name=name, parent=parent, **kw)


def _product(category: Category, name: str, prices: dict[Unit, int], **kw) -> Product:
    slug = slugify(name)
    return Product(
        category=category,
        slug=slug,
        path=f"{category.path}/{slug}",
        name=name,
        search_text=normalize_search(" ".join([name, kw.get("steel_grade") or "", kw.get("gost") or ""])),
        prices=[Price(unit=u, amount_kop=a) for u, a in prices.items()],
        **kw,
    )


def _landing(category: Category, slug: str, name: str, filters: dict, **kw) -> FilterLanding:
    return FilterLanding(category=category, slug=slug, path=f"{category.path}/{slug}", name=name, filters=filters, **kw)


async def seed(session: AsyncSession) -> bool:
    """Заполняет пустую базу. Возвращает False, если данные уже есть."""
    if await session.scalar(select(Category.id).limit(1)):
        return False

    armatura = _category(
        "armatura",
        "Арматура",
        sort=10,
        seo_text="<h2>Арматура для фундамента и монолита</h2><p>Рифлёная А500С и гладкая А1 в прутках 11,7 м. "
        "Режем в размер, продаём от одного прутка.</p>",
    )
    a500c = _category("a500c", "Арматура А500С", armatura, sort=10)
    a1 = _category("a1", "Арматура гладкая А1", armatura, sort=20)

    truba = _category("truba-profilnaya", "Труба профильная", sort=20)
    kvadr = _category("kvadratnaya", "Труба квадратная", truba, sort=10)
    pryam = _category("pryamougolnaya", "Труба прямоугольная", truba, sort=20)

    rebar = dict(gost="ГОСТ 34028-2016", length_m=D("11.7"), base_unit=Unit.METER)
    smooth = dict(gost="ГОСТ 5781-82", length_m=D("11.7"), base_unit=Unit.METER)
    tube = dict(gost="ГОСТ 30245-2003", length_m=D("6"), steel_grade="Ст3", base_unit=Unit.METER)

    products = [
        _product(
            a500c,
            "Арматура 10 мм А500С",
            {Unit.METER: 3050, Unit.TON: 4920000},
            diameter_mm=D(10),
            weight_per_m_kg=D("0.617"),
            steel_grade="А500С",
            **rebar,
        ),
        _product(
            a500c,
            "Арматура 12 мм А500С",
            {Unit.METER: 4325, Unit.TON: 4870000},
            diameter_mm=D(12),
            weight_per_m_kg=D("0.888"),
            steel_grade="А500С",
            **rebar,
        ),
        _product(
            a500c,
            "Арматура 8 мм А500С",
            {Unit.METER: 2150, Unit.TON: 5440000},
            diameter_mm=D(8),
            weight_per_m_kg=D("0.395"),
            steel_grade="А500С",
            **rebar,
        ),
        _product(
            a1,
            "Арматура 10 мм А1",
            {Unit.METER: 3490, Unit.TON: 5650000},
            diameter_mm=D(10),
            weight_per_m_kg=D("0.617"),
            steel_grade="А240",
            **smooth,
        ),
        _product(
            a1,
            "Арматура 8 мм А1",
            {Unit.METER: 2290, Unit.TON: 5790000},
            diameter_mm=D(8),
            weight_per_m_kg=D("0.395"),
            steel_grade="А240",
            **smooth,
        ),
        _product(
            a1,
            "Арматура 12 мм А1",
            {Unit.METER: 4756, Unit.TON: 5341000},
            diameter_mm=D(12),
            weight_per_m_kg=D("0.888"),
            steel_grade="А240",
            **smooth,
        ),
        _product(
            kvadr,
            "Труба профильная 20х20х2",
            {Unit.METER: 9800},
            width_mm=D(20),
            height_mm=D(20),
            thickness_mm=D(2),
            weight_per_m_kg=D("1.06"),
            **tube,
        ),
        _product(
            kvadr,
            "Труба профильная 40х40х2",
            {Unit.METER: 19500},
            width_mm=D(40),
            height_mm=D(40),
            thickness_mm=D(2),
            weight_per_m_kg=D("2.31"),
            **tube,
        ),
        _product(
            kvadr,
            "Труба профильная 40х40х3",
            {Unit.METER: 27000},
            width_mm=D(40),
            height_mm=D(40),
            thickness_mm=D(3),
            weight_per_m_kg=D("3.30"),
            **tube,
        ),
        _product(
            pryam,
            "Труба профильная 40х20х2",
            {Unit.METER: 14900},
            width_mm=D(40),
            height_mm=D(20),
            thickness_mm=D(2),
            weight_per_m_kg=D("1.68"),
            **tube,
        ),
        _product(
            pryam,
            "Труба профильная 40х20х1,5",
            {Unit.METER: 11900},
            width_mm=D(40),
            height_mm=D(20),
            thickness_mm=D("1.5"),
            weight_per_m_kg=D("1.30"),
            **tube,
        ),
        _product(
            pryam,
            "Труба профильная 60х40х2",
            {Unit.METER: 24500},
            width_mm=D(60),
            height_mm=D(40),
            thickness_mm=D(2),
            weight_per_m_kg=D("2.93"),
            **tube,
        ),
    ]

    # Посадочные «по размеру» создаёт генератор (app/catalog/landings.py) после загрузки товаров.
    # Здесь — только пример ручной закрытой комбинации: страница работает, но не индексируется.
    landings = [
        _landing(
            armatura,
            "11-7-m",
            "Арматура 11,7 м",
            {"length_m": 11.7},
            sort=900,
            is_indexable=False,
            h1="Арматура длиной 11,7 м",
        ),
    ]

    session.add_all([armatura, a500c, a1, truba, kvadr, pryam, *products, *landings])
    await session.commit()
    await generate_landings(session, fresh_ids={p.id for p in products})
    return True


async def main() -> None:
    async with SessionLocal() as session:
        created = await seed(session)
    await engine.dispose()
    print("Демо-данные загружены" if created else "База уже заполнена, пропускаю")


if __name__ == "__main__":
    asyncio.run(main())
