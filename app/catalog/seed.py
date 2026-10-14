"""Демо-данные для разработки и тестов. Цены условные.

Запуск: python -m app.catalog.seed
"""

import asyncio
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Category, FilterLanding, Price, Product, Unit
from app.catalog.utils import normalize_search, slugify
from app.core.db import SessionLocal

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
            "Труба профильная 60х40х2",
            {Unit.METER: 24500},
            width_mm=D(60),
            height_mm=D(40),
            thickness_mm=D(2),
            weight_per_m_kg=D("2.93"),
            **tube,
        ),
    ]

    landings = [
        _landing(armatura, "10-mm", "Арматура 10 мм", {"diameter_mm": 10}, sort=10),
        _landing(armatura, "12-mm", "Арматура 12 мм", {"diameter_mm": 12}, sort=20),
        # Пример закрытой комбинации: страница работает, но не индексируется и не попадает в sitemap
        _landing(armatura, "8-mm", "Арматура 8 мм", {"diameter_mm": 8}, sort=30, is_indexable=False),
        _landing(kvadr, "40x40", "Труба профильная 40х40", {"width_mm": 40, "height_mm": 40}, sort=10),
        _landing(pryam, "40x20", "Труба профильная 40х20", {"width_mm": 40, "height_mm": 20}, sort=10),
    ]

    session.add_all([armatura, a500c, a1, truba, kvadr, pryam, *products, *landings])
    await session.commit()
    return True


async def main() -> None:
    async with SessionLocal() as session:
        created = await seed(session)
    print("Демо-данные загружены" if created else "База уже заполнена, пропускаю")


if __name__ == "__main__":
    asyncio.run(main())
