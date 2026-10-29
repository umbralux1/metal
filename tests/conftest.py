import os
import socket
import subprocess
import sys
import time

# Админка в тестах включена с известным паролем
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test-admin-pass"
# Тесты всегда идут на отдельную базу metal_test (создаётся docker/postgres/init.sql)
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://metal:metal@localhost:5433/metal_test"
)

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

import app.models  # noqa: E402, F401  — регистрирует все таблицы, как для Alembic
from app.catalog.landings import generate_landings  # noqa: E402
from app.catalog.models import Redirect  # noqa: E402
from app.catalog.seed import _seed_base  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.delivery.seed import seed_vehicles  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def database():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        # Базовый набор демо-товаров (на нём держатся цены и адреса в тестах).
        # Полный демо-каталог проверяется отдельно — tests/test_demo_catalog.py, с откатом.
        fresh = await _seed_base(session)
        await generate_landings(session, fresh_ids=fresh)
        session.add(Redirect(from_path="/catalog/old-armatura/", to_path="/catalog/armatura/"))
        await session.commit()
        await seed_vehicles(session)  # тарифы доставки, как при запуске сервера
    yield
    await engine.dispose()


def pytest_collection_modifyitems(config, items):
    """Под mutmut (make mutants) браузерные тесты не запускаются: они не проверяют код корзины и заявок напрямую."""
    if "MUTANT_UNDER_TEST" in os.environ:
        skip = pytest.mark.skip(reason="браузерные тесты под mutmut не запускаются")
        for item in items:
            if item.path.name.startswith("test_browser_"):
                item.add_marker(skip)


@pytest.fixture(autouse=True)
def lead_limit_off(request, monkeypatch):
    """Тесты шлют десятки заявок с одного адреса — порог им не мешает. Настоящий порог — в test_lead_limit.py."""
    if request.module.__name__.endswith("test_lead_limit"):
        return
    monkeypatch.setattr(settings, "lead_limit", 1_000_000)


@pytest_asyncio.fixture
async def admin():
    """Клиент, вошедший в админку."""
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.post("/admin/login", data={"username": "admin", "password": "test-admin-pass"})
        assert r.status_code == 302
        yield c


@pytest_asyncio.fixture(scope="session")
async def client():
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def migrations_db(monkeypatch):
    """Отдельная пустая база, которую строят только миграции Alembic (как на Render)."""
    url = make_url(settings.database_url).set(database="metal_migrations")
    admin = create_engine(url.set(database="postgres", drivername="postgresql+psycopg"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS metal_migrations WITH (FORCE)"))
        conn.execute(text("CREATE DATABASE metal_migrations"))
    monkeypatch.setattr(settings, "database_url", url.render_as_string(hide_password=False))
    sync_url = url.set(drivername="postgresql+psycopg")
    yield create_engine(sync_url)
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS metal_migrations WITH (FORCE)"))
    admin.dispose()


@pytest.fixture(scope="session")
def live_server():
    """Сайт в отдельном процессе на свободном порту — браузеру нужен настоящий HTTP. База — тестовая."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = subprocess.Popen(  # noqa: S603 — свой сервер из своего окружения
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        env=os.environ.copy(),
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                httpx.get(url + "/", timeout=1)
                break
            except httpx.TransportError:
                time.sleep(0.1)
        yield url
    finally:
        server.terminate()
        server.wait(timeout=10)
