"""Скрытые разделы: выключенный раздел («Активен» снят) прячет всё, что внутри.

Подразделы, товары и страницы размеров скрытого раздела не видны нигде: ни страницами, ни в меню, каталоге,
sitemap, поиске и подсказках. Их адреса отдают 301 на ближайший видимый раздел выше (или на каталог) — ссылки
из поисковиков не ведут на 404. В базе и в админке ничего не удаляется: включили раздел — вернулось всё.

На этапе запуска скрыты 8 разделов (решение от 22.10.2026, вернуть позже): штакетник, заборы, крепёж, фитинги,
стройматериалы, петли, профнастил, заглушки. Миграция 0006 выключает их в работающей базе, демо-каталог
создаёт их выключенными в новой.
"""

from xml.etree import ElementTree

import pytest
import pytest_asyncio
from sqlalchemy import select, text, update

from app.catalog.demo_catalog import _tree
from app.catalog.models import Category, Product
from app.catalog.nav import reset_nav_cache
from app.core.db import SessionLocal
from tests.helpers import run_alembic

HIDDEN_AT_LAUNCH = {
    "shtaketnik",
    "zabory",
    "krepezh",
    "fitingi",
    "stroymaterialy",
    "petli",
    "profnastil",
    "zaglushki",
}

PIPE = "truba-profilnaya"
PIPE_SUB = f"{PIPE}/kvadratnaya"
PIPE_LANDING = f"{PIPE_SUB}/40x40"
PIPE_PRODUCT = f"{PIPE_LANDING}/40x40x2"


async def set_active(path: str, active: bool) -> None:
    async with SessionLocal() as s:
        await s.execute(update(Category).where(Category.path == path).values(is_active=active))
        await s.commit()
    reset_nav_cache()


@pytest_asyncio.fixture
async def hidden_pipe():
    """Скрыт корневой раздел «Труба профильная»; подразделы и товары в базе по-прежнему «Активен»."""
    await set_active(PIPE, False)
    yield
    await set_active(PIPE, True)


async def sitemap_paths(client) -> set[str]:
    xml = (await client.get("/sitemap.xml")).content
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return {el.text.split("/catalog/", 1)[-1] for el in ElementTree.fromstring(xml).findall("s:url/s:loc", ns)}


# ---------- Скрытый корневой раздел ----------


@pytest.mark.parametrize("path", [PIPE, PIPE_SUB, PIPE_LANDING, PIPE_PRODUCT])
async def test_everything_inside_redirects_to_catalog(client, hidden_pipe, path):
    r = await client.get(f"/catalog/{path}/")
    assert (r.status_code, r.headers.get("location")) == (301, "/catalog/"), path


async def test_hidden_section_is_gone_from_menu_home_and_catalog(client, hidden_pipe):
    for url in ("/", "/catalog/", "/catalog/armatura/"):
        html = (await client.get(url)).text
        assert f'href="/catalog/{PIPE}/' not in html, url


async def test_hidden_section_is_gone_from_sitemap(client, hidden_pipe):
    assert not [p for p in await sitemap_paths(client) if p.startswith(PIPE)]


async def test_hidden_section_is_gone_from_search_and_suggest(client, hidden_pipe):
    search = (await client.get("/search/", params={"q": "труба 40х40"})).text
    assert f"/catalog/{PIPE}/" not in search
    suggest = (await client.get("/api/suggest/", params={"q": "труба"})).text
    assert f"/catalog/{PIPE}/" not in suggest


async def test_enabling_section_brings_everything_back(client):
    await set_active(PIPE, False)
    await set_active(PIPE, True)
    for path in (PIPE, PIPE_SUB, PIPE_LANDING, PIPE_PRODUCT):
        assert (await client.get(f"/catalog/{path}/")).status_code == 200, path
    assert PIPE_PRODUCT + "/" in await sitemap_paths(client)


async def test_hidden_section_stays_in_database_and_admin(admin, hidden_pipe):
    async with SessionLocal() as s:
        product = await s.scalar(select(Product).where(Product.path == PIPE_PRODUCT))
    assert product is not None and product.is_active  # товар не тронут — скрыт разделом
    assert (await admin.get(f"/admin/product/edit/{product.id}")).status_code == 200


# ---------- Скрытый подраздел внутри видимого раздела ----------


@pytest_asyncio.fixture
async def hidden_a1():
    await set_active("armatura/a1", False)
    yield
    await set_active("armatura/a1", True)


async def test_hidden_subsection_products_leave_parent_listing(client, hidden_a1):
    for url in ("/catalog/armatura/", "/catalog/armatura/12-mm/"):
        html = (await client.get(url)).text
        assert "12-mm-a1" not in html, url  # гладкая А1 скрыта вместе с подразделом
        assert "12-mm-a500s" in html, url  # А500С на месте


async def test_hidden_subsection_product_redirects_to_parent(client, hidden_a1):
    async with SessionLocal() as s:
        path = await s.scalar(select(Product.path).where(Product.path.like("armatura/%12-mm-a1")))
    r = await client.get(f"/catalog/{path}/")
    assert r.status_code == 301 and r.headers["location"] in ("/catalog/armatura/", "/catalog/armatura/12-mm/")


# ---------- Разделы, скрытые на запуске ----------


def test_demo_catalog_creates_launch_hidden_sections_inactive():
    roots = {node.slug: node for node in _tree()}
    assert HIDDEN_AT_LAUNCH <= roots.keys()
    for slug, node in roots.items():
        assert node.active is (slug not in HIDDEN_AT_LAUNCH), slug


def test_migration_hides_launch_sections_in_existing_database(migrations_db):
    run_alembic("upgrade", "0005")
    with migrations_db.begin() as conn:
        for slug in [*HIDDEN_AT_LAUNCH, "armatura"]:
            conn.execute(text("INSERT INTO categories (slug, path, name) VALUES (:s, :s, :s)"), {"s": slug})
    run_alembic("upgrade", "head")
    with migrations_db.connect() as conn:
        active = dict(conn.execute(text("SELECT path, is_active FROM categories")).all())
    assert active == {**dict.fromkeys(HIDDEN_AT_LAUNCH, False), "armatura": True}
    run_alembic("downgrade", "0005")
    with migrations_db.connect() as conn:
        assert all(conn.execute(text("SELECT is_active FROM categories")).scalars())
    migrations_db.dispose()
