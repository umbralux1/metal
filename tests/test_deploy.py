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


def test_render_without_database_url_fails_with_clear_message(monkeypatch):
    import pytest
    from pydantic import ValidationError

    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(_env_file=None)


def test_main_server_options():
    from main import server_options

    local = server_options({})
    assert local["host"] == "127.0.0.1" and local["port"] == 8000 and local["reload"] is True
    hosted = server_options({"PORT": "10000"})
    assert hosted["host"] == "0.0.0.0" and hosted["port"] == 10000 and hosted["reload"] is False


def test_render_env_file_only_on_render(monkeypatch):
    from app.core.config import RENDER_ENV_FILE, env_files

    monkeypatch.delenv("RENDER", raising=False)
    assert env_files() == (".env",)
    monkeypatch.setenv("RENDER", "true")
    assert env_files() == (".env", RENDER_ENV_FILE)
    assert RENDER_ENV_FILE.is_file()


def test_render_env_file_values_and_dashboard_override(monkeypatch):
    from app.core.config import RENDER_ENV_FILE

    for key in ("ADMIN_PASSWORD", "ADMIN_USERNAME", "SEED_DEMO", "ALLOW_INDEXING", "SECRET_KEY", "PHONE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/metal")

    s = Settings(_env_file=RENDER_ENV_FILE)
    assert s.seed_demo is True and s.allow_indexing is False
    assert s.admin_username == "admin" and s.admin_password
    assert len(s.secret_key) >= 32
    assert "DATABASE_URL" not in RENDER_ENV_FILE.read_text().replace("# DATABASE_URL", "")

    # Переменная из панели Render важнее файла
    monkeypatch.setenv("ADMIN_PASSWORD", "from-dashboard")
    monkeypatch.setenv("SEED_DEMO", "false")
    s = Settings(_env_file=RENDER_ENV_FILE)
    assert s.admin_password == "from-dashboard" and s.seed_demo is False


async def test_static_files_are_versioned_and_cached(client):
    """Стили и скрипты подключаются с отпечатком версии: после обновления браузер берёт новый файл сам."""
    import re

    html = (await client.get("/")).text
    css = re.search(r'href="(/static/css/main\.css\?v=[0-9a-f]{10})"', html)
    assert css, "main.css без версии — после обновления браузер покажет старые стили"
    r = await client.get(css.group(1))
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=31536000, immutable"
    # Без версии — браузер каждый раз сверяется с сервером
    r = await client.get("/static/fonts/golos-text.woff")
    assert r.headers["cache-control"] == "no-cache"


def test_static_hash_changes_with_content(tmp_path, monkeypatch):
    from app.core import static

    monkeypatch.setattr(static, "STATIC_DIR", tmp_path)
    static._hashes.clear()
    f = tmp_path / "a.css"
    f.write_text("body{color:red}")
    first = static.static_url("a.css")
    f.write_text("body{color:blue}")
    import os

    os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 5))
    assert static.static_url("a.css") != first
    assert static.static_url("missing.css") == "/static/missing.css"
    static._hashes.clear()


def test_templates_link_static_only_through_static_url():
    """Стили, скрипты и картинки подключаются только через static_url() — иначе после обновления
    браузер покажет старую версию из кэша. Исключение — шрифты: их адрес должен совпадать с url() в CSS."""
    import re
    from pathlib import Path

    templates = Path(__file__).resolve().parent.parent / "app" / "templates"
    bad = []
    for file in templates.rglob("*.html"):
        for n, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
            for link in re.findall(r"""["'](/static/[^"'?]+)""", line):
                if not link.startswith("/static/fonts/"):
                    bad.append(f"{file.relative_to(templates)}:{n} {link}")
    assert not bad, "Подключите через {{ static_url('...') }}: " + ", ".join(bad)
