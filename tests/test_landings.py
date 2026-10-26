"""Генератор посадочных «по размеру»: что создаёт, что не трогает, что закрывает от индекса."""

from decimal import Decimal

from sqlalchemy import select

from app.catalog.landing_rules import LandingRule
from app.catalog.landings import build_texts, generate_landings, size_slug
from app.catalog.models import FilterLanding, Product
from app.core.db import SessionLocal
from app.seo.meta import with_price
from tests.helpers import PageInfo

RUB = "\u00a0₽"  # format_rub ставит неразрывный пробел перед знаком рубля


async def _landing(path: str) -> FilterLanding | None:
    async with SessionLocal() as session:
        return await session.scalar(select(FilterLanding).where(FilterLanding.path == path))


def test_size_slug_format():
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
    # Размер с одним товаром: посадочная есть (как родитель адреса товара), но закрыта от индекса —
    # запрос закрывает карточка товара
    single = await _landing("truba-profilnaya/pryamougolnaya/60x40")
    assert single.is_generated and not single.is_indexable


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
    assert html.index('href="/catalog/armatura/8-mm/"') < html.index('href="/catalog/armatura/12-mm/"')


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
        product = await session.scalar(select(Product).where(Product.slug == "40x20x1-5"))
        product.is_active = False
        await session.commit()
        report = await generate_landings(session)
    assert "truba-profilnaya/pryamougolnaya/40x20" in report.hidden
    assert not (await _landing("truba-profilnaya/pryamougolnaya/40x20")).is_indexable

    async with SessionLocal() as session:
        product = await session.scalar(select(Product).where(Product.slug == "40x20x1-5"))
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


async def test_products_live_inside_size_landing():
    """Товар размера лежит внутри посадочной: …/kvadratnaya/40x40/40x40x2/, slug — без названия раздела."""
    async with SessionLocal() as session:
        paths = set(await session.scalars(select(Product.path)))
    assert "truba-profilnaya/kvadratnaya/40x40/40x40x2" in paths
    assert "truba-profilnaya/pryamougolnaya/60x40/60x40x2" in paths  # одна толщина — родитель закрыт от индекса
    assert "armatura/12-mm/12-mm-a500s" in paths  # выше подраздела А500С: размер объединяет обе марки


async def test_category_lists_products_by_category_not_url(client):
    """Подраздел «А500С» показывает свои товары, хотя их адреса лежат в посадочных размера."""
    html = (await client.get("/catalog/armatura/a500c/")).text
    table = html.split('class="products"', 1)[1].split("</table>", 1)[0]
    assert "12-mm-a500s" in table and "12-mm-a1" not in table


async def test_old_long_slug_moves_with_redirect():
    """Товар со старым адресом (как на Render до обновления) переезжает в посадочную, со старого — 301."""
    async with SessionLocal() as session:
        product = await session.scalar(select(Product).where(Product.slug == "20x20x2"))
        product.slug = "truba-profilnaya-20x20x2"
        product.path = "truba-profilnaya/kvadratnaya/truba-profilnaya-20x20x2"
        await session.commit()
        report = await generate_landings(session)
    assert "truba-profilnaya/kvadratnaya/20x20/20x20x2" in report.moved
    from tests.test_admin import new_client

    async with new_client() as site:
        r = await site.get("/catalog/truba-profilnaya/kvadratnaya/truba-profilnaya-20x20x2/")
        assert (r.status_code, r.headers["location"]) == (301, "/catalog/truba-profilnaya/kvadratnaya/20x20/20x20x2/")


async def test_product_card_seo_blocks(client):
    r = await client.get("/catalog/truba-profilnaya/pryamougolnaya/40x20/40x20x2/")
    assert r.status_code == 200
    page = PageInfo(r.text)
    assert page.title == f"Труба профильная прямоугольная 40х20х2 купить в Москве — цена 149{RUB}/м"
    assert page.description.startswith(f"Труба профильная прямоугольная 40х20х2: 149{RUB}/м, 6 м — 894{RUB}.")
    html = r.text
    # Другие толщины того же размера и соседние размеры
    assert 'href="/catalog/truba-profilnaya/pryamougolnaya/40x20/40x20x1-5/"' in html
    assert "Труба профильная 40х20: другие варианты" in html
    assert 'href="/catalog/truba-profilnaya/pryamougolnaya/40x20/"' in html
    # Текст из данных товара и цена за штуку
    assert "Вес 1 метра — 1,68 кг, в тонне около 595 м." in html
    assert f"894{RUB} за штуку 6 м" in html
