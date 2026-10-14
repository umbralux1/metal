"""SEO-контракт: если тест падает, страница сломана для поисковика."""

import re
from xml.etree import ElementTree

import pytest

from app.core.config import settings
from tests.helpers import PageInfo

SITE = settings.site_url


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
    assert "Арматура 12 мм А500С" in r.text and "Арматура 12 мм А1" in r.text
    assert "Арматура 10 мм" not in r.text.split("<h1>", 1)[1].split("По размеру", 1)[0]
    assert "А500С</a>" in r.text


async def test_landing_by_two_dimensions(client):
    r = await client.get("/catalog/truba-profilnaya/kvadratnaya/40x40/")
    assert r.status_code == 200
    assert "40х40х2" in r.text and "40х40х3" in r.text
    assert "20х20х2</a>" not in r.text


async def test_non_indexable_landing(client):
    r = await client.get("/catalog/armatura/8-mm/")
    assert r.status_code == 200
    assert PageInfo(r.text).robots == "noindex, follow"


async def test_product_page_jsonld(client):
    r = await client.get("/catalog/armatura/a500c/armatura-12-mm-a500s/")
    assert r.status_code == 200
    page = PageInfo(r.text)
    product = next(b for b in page.jsonld if b["@type"] == "Product")
    assert product["offers"]["price"] == "43.25"
    assert product["offers"]["priceCurrency"] == "RUB"
    assert product["offers"]["availability"].endswith("InStock")
    crumbs = next(b for b in page.jsonld if b["@type"] == "BreadcrumbList")
    names = [i["name"] for i in crumbs["itemListElement"]]
    assert names == ["Главная", "Каталог", "Арматура", "Арматура А500С", "Арматура 12 мм А500С"]


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
    r = await client.get("/catalog/armatura/a500c/armatura-12-mm-a500s/?page=2")
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
    assert "/catalog/armatura/8-mm/" not in paths  # закрытая комбинация
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
