"""Настройки для хостинга (Render): адрес базы, адрес сайта, режим закрытой копии."""

import httpx
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.config import Settings, settings
from app.seo.middleware import NoIndexMiddleware


def test_render_database_url_gets_async_driver():
    s = Settings(database_url="postgresql://metal:pw@dpg-123:5432/metal", _env_file=None)
    assert s.database_url == "postgresql+psycopg://metal:pw@dpg-123:5432/metal"
    s = Settings(database_url="postgres://u:p@h/db", _env_file=None)
    assert s.database_url == "postgresql+psycopg://u:p@h/db"
    s = Settings(database_url="postgresql+psycopg://u:p@h/db", _env_file=None)
    assert s.database_url == "postgresql+psycopg://u:p@h/db"


def test_site_url_from_render(monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://metal-web.onrender.com")
    monkeypatch.delenv("SITE_URL", raising=False)
    assert Settings(_env_file=None).site_url == "https://metal-web.onrender.com"
    # Явный SITE_URL (свой домен) важнее адреса Render
    assert Settings(site_url="https://metall.ru/", _env_file=None).site_url == "https://metall.ru"


async def test_robots_closed_when_indexing_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "allow_indexing", False)
    r = await client.get("/robots.txt")
    assert r.text == "User-agent: *\nDisallow: /\n"


async def test_noindex_header_middleware():
    async def page(request):
        return PlainTextResponse("ok", headers={"X-Robots-Tag": "index"})

    app = NoIndexMiddleware(Starlette(routes=[Route("/", page)]))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/")
    assert r.headers.get_list("x-robots-tag") == ["noindex, nofollow"]
