"""Общий SEO-тест: страница каждого типа. Новый тип публичной страницы — добавить в INDEXABLE или NOINDEX."""

import pytest

from app.core.config import settings
from tests.helpers import PageInfo

SITE = settings.site_url

# Адрес → типы JSON-LD, которые обязаны быть на странице
INDEXABLE = {
    "/": {"Organization"},
    "/catalog/": {"BreadcrumbList"},
    "/catalog/armatura/": {"BreadcrumbList", "ItemList"},
    "/catalog/armatura/12-mm/": {"BreadcrumbList", "ItemList"},
    "/catalog/armatura/12-mm/12-mm-a500s/": {"BreadcrumbList", "Product"},
    "/contacts/": {"BreadcrumbList", "Store"},
    "/delivery/": {"BreadcrumbList"},
}

# Служебные страницы: открыты людям, закрыты от индекса
NOINDEX = ["/cart/", "/search/", "/search/?q=труба", "/catalog/armatura/?sort=price"]


async def sitemap(client) -> str:
    return (await client.get("/sitemap.xml")).text


@pytest.mark.parametrize("url", INDEXABLE)
async def test_indexable_page(client, url):
    r = await client.get(url)
    assert r.status_code == 200, url
    page = PageInfo(r.text)
    assert len(page.h1) == 1, f"{url}: должен быть ровно один h1, найдено {len(page.h1)}"
    assert page.title, f"{url}: нет title"
    assert page.description, f"{url}: нет meta description"
    assert page.canonical == SITE + url, f"{url}: canonical {page.canonical}"
    assert page.robots is None, f"{url}: страница закрыта от индекса ({page.robots})"
    assert f"<loc>{SITE}{url}</loc>" in await sitemap(client), f"{url}: нет в sitemap.xml"
    missing = INDEXABLE[url] - page.jsonld_types()
    assert not missing, f"{url}: нет разметки {missing}"


@pytest.mark.parametrize("url", NOINDEX)
async def test_service_page_is_noindex(client, url):
    r = await client.get(url)
    assert r.status_code == 200, url
    page = PageInfo(r.text)
    assert page.robots and page.robots.startswith("noindex"), f"{url}: должна быть закрыта noindex"
    assert len(page.h1) == 1, url


async def test_titles_and_descriptions_are_unique(client):
    pages = [PageInfo((await client.get(url)).text) for url in INDEXABLE]
    titles = [p.title for p in pages]
    descriptions = [p.description for p in pages]
    assert len(set(titles)) == len(titles), titles
    assert len(set(descriptions)) == len(descriptions), descriptions
