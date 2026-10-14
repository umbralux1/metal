"""SEO-контракт: если тест падает, страница сломана для поисковика."""

import re
from xml.etree import ElementTree

import pytest

from app.core.config import settings
from tests.helpers import PageInfo

SITE = settings.site_url


def products_table(html: str) -> str:
    """HTML таблицы товаров — чтобы проверять, что попало именно в список, а не в меню или ссылки."""
    return html.split('class="products"', 1)[1].split("</table>", 1)[0]


async def test_category_page(client):
    r = await client.get("/catalog/armatura/")
    assert r.status_code == 200
    page = PageInfo(r.text)
    assert page.h1 == ["Арматура"]
    assert page.title.startswith("Арматура купить в Москве")
    assert page.canonical == f"{SITE}/catalog/armatura/"
    assert page.robots is None
    assert {"BreadcrumbList", "ItemList"} <= page.jsonld_types()
    # Товары подразделов видны на странице раздела, есть ссылки на посадочные «по размеру»
    assert "Арматура 12 мм А500С" in r.text
    assert 'href="/catalog/armatura/12-mm/"' in r.text


async def test_landing_filters_products_and_builds_title(client):
    r = await client.get("/catalog/armatura/12-mm/")
    assert r.status_code == 200
    page = PageInfo(r.text)
    assert page.h1 == ["Арматура 12 мм"]
    assert "от 43,25 ₽" in page.title
    table = products_table(r.text)
    assert "12-mm-a500s" in table and "12-mm-a1" in table
    assert "10-mm-a" not in table


async def test_landing_by_two_dimensions(client):
    r = await client.get("/catalog/truba-profilnaya/kvadratnaya/40x40/")
    assert r.status_code == 200
    table = products_table(r.text)
    assert "40x40x2" in table and "40x40x3" in table
    assert "20x20x2" not in table and "40x20x2" not in table


async def test_non_indexable_landing(client):
    r = await client.get("/catalog/armatura/11-7-m/")
    assert r.status_code == 200
    assert PageInfo(r.text).robots == "noindex, follow"


async def test_product_page_jsonld(client):
    r = await client.get("/catalog/armatura/12-mm/12-mm-a500s/")
    assert r.status_code == 200
    page = PageInfo(r.text)
    product = next(b for b in page.jsonld if b["@type"] == "Product")
    assert product["offers"]["price"] == "43.25"
    assert product["offers"]["priceCurrency"] == "RUB"
    assert product["offers"]["availability"].endswith("InStock")
    crumbs = next(b for b in page.jsonld if b["@type"] == "BreadcrumbList")
    names = [i["name"] for i in crumbs["itemListElement"]]
    # Товар лежит внутри посадочной размера — она тоже в крошках
    assert names == ["Главная", "Каталог", "Арматура", "Арматура 12 мм", "Арматура 12 мм А500С"]


@pytest.mark.parametrize(
    ("url", "location"),
    [
        ("/catalog/armatura", "/catalog/armatura/"),
        ("/Catalog/Armatura/", "/catalog/armatura/"),
        ("/catalog//armatura/", "/catalog/armatura/"),
        ("/catalog/armatura?page=1", "/catalog/armatura/?page=1"),
        ("/catalog/old-armatura/", "/catalog/armatura/"),  # таблица редиректов
    ],
)
async def test_redirects_301(client, url, location):
    r = await client.get(url)
    assert r.status_code == 301
    assert r.headers["location"] == location


async def test_sort_and_pagination_are_noindex(client):
    r = await client.get("/catalog/armatura/?sort=price")
    page = PageInfo(r.text)
    assert page.robots == "noindex, follow"
    assert page.canonical == f"{SITE}/catalog/armatura/"


async def test_404(client):
    assert (await client.get("/catalog/net-takogo/")).status_code == 404
    assert (await client.get("/catalog/armatura/?page=99")).status_code == 404
    r = await client.get("/catalog/armatura/12-mm/12-mm-a500s/?page=2")
    assert r.status_code == 404


async def test_robots_txt(client):
    r = await client.get("/robots.txt")
    assert r.status_code == 200
    assert f"Sitemap: {SITE}/sitemap.xml" in r.text


async def _sitemap_paths(client) -> list[str]:
    r = await client.get("/sitemap.xml")
    assert r.status_code == 200
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [el.text for el in ElementTree.fromstring(r.content).findall("s:url/s:loc", ns)]
    return [loc.removeprefix(SITE) for loc in locs]


async def test_sitemap_contents(client):
    paths = await _sitemap_paths(client)
    assert "/catalog/armatura/12-mm/" in paths
    assert "/catalog/armatura/11-7-m/" not in paths  # закрытая комбинация
    assert len(paths) == len(set(paths))


async def test_every_sitemap_url_is_clean(client):
    """Каждый URL из sitemap: 200, один H1, canonical на себя, без noindex, title и description есть."""
    for path in await _sitemap_paths(client):
        r = await client.get(path)
        assert r.status_code == 200, path
        page = PageInfo(r.text)
        assert len(page.h1) == 1, path
        assert page.canonical == SITE + path, path
        assert page.robots is None, path
        assert page.title and page.description, path
        assert re.search(r"<html lang=\"ru\">", r.text), path


async def test_search(client):
    r = await client.get("/search/", params={"q": "ТРУБА 40х40"})
    assert r.status_code == 200
    page = PageInfo(r.text)
    assert page.robots == "noindex, follow"
    table = products_table(r.text)
    assert "40x40x2" in table and "40x40x3" in table and "20x20x2" not in table


async def test_search_nothing_found(client):
    r = await client.get("/search/", params={"q": "титан"})
    assert r.status_code == 200
    assert "ничего не нашли" in r.text


async def test_header_nav_lists_top_categories(client):
    """Меню «Каталог» в шапке — вертикальный список всех корневых разделов со значками."""
    r = await client.get("/catalog/armatura/")
    nav = r.text.split('class="catalog-panel"', 1)[1].split("</nav>", 1)[0]
    assert 'href="/catalog/armatura/" aria-current="page"' in nav
    assert 'href="/catalog/truba-profilnaya/"' in nav
    assert nav.count('class="icon iso"') >= 2 and 'class="chev"' in nav
    # Горизонтальной полосы разделов больше нет
    assert 'class="cat-nav"' not in r.text


async def test_home_shows_full_catalog_as_list(client):
    """На главной весь каталог виден сразу: список разделов идёт сразу после H1."""
    html = (await client.get("/")).text
    menu = html.split('class="home-menu"', 1)[1].split("</nav>", 1)[0]
    assert 'href="/catalog/armatura/"' in menu and 'href="/catalog/truba-profilnaya/"' in menu
    assert html.index('class="home-title"') < html.index('class="home-menu"') < html.index('class="home-intro"')


def test_iso_icons_cover_brief_categories():
    from app.catalog.iso_icons import CATEGORY_SHAPES, SHAPES, iso_icon

    assert {shape for _, shape in CATEGORY_SHAPES} <= set(SHAPES)
    svg = iso_icon("armatura")
    assert svg.startswith('<svg class="icon iso"') and "vector-effect" in svg
    assert iso_icon("neizvestnyy-razdel") == iso_icon("eshche-odin")  # запасной значок


async def test_product_page_has_section_drawing(client):
    r = await client.get("/catalog/truba-profilnaya/kvadratnaya/40x40/40x40x2/")
    assert 'class="section-drawing"' in r.text
    assert "t = 2" in r.text


@pytest.mark.parametrize("url", ["/", "/catalog/armatura/", "/health", "/sitemap.xml"])
async def test_head_requests(client, url):
    r = await client.head(url)
    assert r.status_code == 200
    assert r.content == b""


async def test_head_keeps_redirects(client):
    r = await client.head("/catalog/armatura")
    assert r.status_code == 301
