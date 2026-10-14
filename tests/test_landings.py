"""Генератор посадочных «по размеру»: что создаёт, что не трогает, что закрывает от индекса."""

from decimal import Decimal

from sqlalchemy import select

from app.catalog.landing_rules import LandingRule
from app.catalog.landings import build_texts, generate_landings, num, size_slug
from app.catalog.models import FilterLanding, Product
from app.core.db import SessionLocal
from app.seo.meta import with_price
from tests.helpers import PageInfo

RUB = "\u00a0₽"  # format_rub ставит неразрывный пробел перед знаком рубля


async def _landing(path: str) -> FilterLanding | None:
    async with SessionLocal() as session:
        return await session.scalar(select(FilterLanding).where(FilterLanding.path == path))


def test_number_and_slug_format():
    assert num(Decimal("12.00")) == "12" and num(Decimal("6.50")) == "6,5" and num(Decimal("0.8880")) == "0,888"
    rule = LandingRule("x", ("width_mm", "height_mm"), "Труба", "от одной трубы")
    assert size_slug(rule, (Decimal("40"), Decimal("20"))) == "40x20"
    assert size_slug(rule, (Decimal("6.5"),)) == "6-5-mm"


def test_price_token():
    assert with_price("Арматура 12 мм {price}: в наличии", 4325) == f"Арматура 12 мм от 43,25{RUB}: в наличии"
    assert with_price("Арматура 12 мм {price}: в наличии", None) == "Арматура 12 мм: в наличии"
    assert with_price("Без цены", 100) == "Без цены"


async def test_seed_creates_landings_for_sizes_with_two_products():
    rebar = await _landing("armatura/12-mm")
    assert rebar.is_generated and rebar.is_indexable
    assert rebar.filters == {"diameter_mm": 12}
    # Все товары размера лежат в одном подразделе — посадочная там же
    tube = await _landing("truba-profilnaya/pryamougolnaya/40x20")
    assert tube.is_generated and tube.filters == {"width_mm": 40, "height_mm": 20}
    # Размер с одним товаром посадочной не получает: его закрывает страница товара
    assert await _landing("truba-profilnaya/pryamougolnaya/60x40") is None
    assert await _landing("truba-profilnaya/kvadratnaya/20x20") is None


async def test_generated_page_meta_and_text(client):
    r = await client.get("/catalog/armatura/12-mm/")
    page = PageInfo(r.text)
    assert page.h1 == ["Арматура 12 мм"]
    assert page.title == f"Арматура 12 мм купить в Москве от 43,25{RUB} — цена за метр и тонну"
    assert page.description.startswith(
        f"Арматура 12 мм от 43,25{RUB}: 2 позиции в наличии (А240 и А500С; длина 11,7 м)"
    )
    assert "{price}" not in r.text
    assert "Вес 1 метра: 0,888 кг — в тонне около 1126 м" in r.text
    assert "фундамент" in r.text


async def test_tube_landing_lists_wall_thicknesses(client):
    r = await client.get("/catalog/truba-profilnaya/pryamougolnaya/40x20/")
    assert r.status_code == 200
    assert "Толщина стенки: 1,5 мм и 2 мм" in r.text
    assert "Вес 1 метра: от 1,3 до 1,68 кг" in r.text


async def test_category_links_to_generated_sizes(client):
    html = (await client.get("/catalog/armatura/")).text
    for size in ("8-mm", "10-mm", "12-mm"):
        assert f'href="/catalog/armatura/{size}/"' in html
    assert html.index("/catalog/armatura/8-mm/") < html.index("/catalog/armatura/12-mm/")


async def test_generator_is_idempotent_and_keeps_manual_landings():
    async with SessionLocal() as session:
        before = {item.path for item in await session.scalars(select(FilterLanding))}
        report = await generate_landings(session)
        after = {item.path for item in await session.scalars(select(FilterLanding))}
    assert not report.created and before == after
    manual = await _landing("armatura/11-7-m")
    assert not manual.is_generated and not manual.is_indexable and manual.h1 == "Арматура длиной 11,7 м"


async def test_size_disappears_landing_goes_noindex_then_returns():
    async with SessionLocal() as session:
        product = await session.scalar(select(Product).where(Product.slug == "truba-profilnaya-40x20x1-5"))
        product.is_active = False
        await session.commit()
        report = await generate_landings(session)
    assert "truba-profilnaya/pryamougolnaya/40x20" in report.hidden
    assert not (await _landing("truba-profilnaya/pryamougolnaya/40x20")).is_indexable

    async with SessionLocal() as session:
        product = await session.scalar(select(Product).where(Product.slug == "truba-profilnaya-40x20x1-5"))
        product.is_active = True
        await session.commit()
        await generate_landings(session)
    assert (await _landing("truba-profilnaya/pryamougolnaya/40x20")).is_indexable


def test_long_title_drops_tail():
    rule = LandingRule("x", ("diameter_mm",), "Труба электросварная прямошовная", "от одной трубы")

    class P:  # минимальный товар для текста
        steel_grade = gost = length_m = thickness_mm = weight_per_m_kg = None
        in_stock = True
        base_unit = "m"
        prices = []

        def price_for(self, unit):
            return None

    texts = build_texts(rule, (Decimal("159"),), [P()])
    assert texts.title == "Труба электросварная прямошовная 159 мм купить в Москве {price}"
