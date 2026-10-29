"""Ограничение входа в админку: 5 неудачных попыток за 15 минут с адреса, счёт в базе (specs/003-admin-login-limit).

У каждого теста свой адрес подключения — тесты не мешают друг другу и фикстуре `admin`.
Модель таблицы попыток импортируется внутри функций: до реализации её нет, и падать должен каждый тест по отдельности.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from itertools import count

import httpx
from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import SessionLocal
from app.leads.fingerprint import client_fingerprint
from app.main import app as fastapi_app

PASSWORD = "test-admin-pass"
WRONG = "wrong-pass-7731"
BLOCKED = "Слишком много попыток, попробуйте через 15 минут"
INVALID = "Invalid credentials."
_addresses = count(10)


@asynccontextmanager
async def visitor(ip: str | None = None):
    """Посетитель страницы входа со своим адресом подключения и своими cookie."""
    ip = ip or f"198.51.100.{next(_addresses)}"
    transport = httpx.ASGITransport(app=fastapi_app, client=(ip, 51000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        c.ip = ip  # type: ignore[attr-defined]
        yield c


async def login(c: httpx.AsyncClient, password: str = WRONG, username: str = "admin") -> httpx.Response:
    return await c.post("/admin/login", data={"username": username, "password": password})


async def fail(c: httpx.AsyncClient, n: int) -> list[int]:
    return [(await login(c)).status_code for _ in range(n)]


def failure_model():
    from app.admin.models import AdminLoginFailure

    return AdminLoginFailure


async def failures_of(ip: str) -> int:
    model = failure_model()
    async with SessionLocal() as s:
        fingerprint = client_fingerprint(ip, settings.secret_key)
        return await s.scalar(select(func.count()).select_from(model).where(model.client_hash == fingerprint)) or 0


async def add_failures(ip: str, n: int, minutes_ago: int = 0) -> None:
    """Неудачные попытки, записанные «другой копией сайта» или «до перезапуска»."""
    model = failure_model()
    async with SessionLocal() as s:
        fingerprint = client_fingerprint(ip, settings.secret_key)
        for _ in range(n):
            s.add(
                model(client_hash=fingerprint, created_at=func.now() - func.make_interval(0, 0, 0, 0, 0, minutes_ago))
            )
        await s.commit()


async def test_five_failures_block_even_correct_password():
    """003:FR-001: после 5 неверных паролей за 15 минут вход с адреса закрыт даже с верным паролем."""
    async with visitor() as c:
        assert 302 not in await fail(c, 5)
        r = await login(c, PASSWORD)
        assert r.status_code != 302


async def test_attempts_from_blocked_address_are_not_counted():
    """003:FR-002: попытки с закрытого адреса в счёт не идут — блокировка не продлевается."""
    async with visitor() as c:
        await fail(c, 5)
        await fail(c, 3)
        await login(c, PASSWORD)
        assert await failures_of(c.ip) == 5


async def test_old_failures_and_other_addresses_do_not_block():
    """003:FR-003: ошибки старше 15 минут не считаются; блокировка одного адреса не мешает другому."""
    async with visitor() as c:
        await add_failures(c.ip, 5, minutes_ago=16)
        assert (await login(c, PASSWORD)).status_code == 302
    async with visitor() as blocked, visitor() as other:
        await fail(blocked, 5)
        assert (await login(other, PASSWORD)).status_code == 302


async def test_login_page_and_admin_pages_are_not_counted():
    """003:FR-003: открытие страницы входа и страниц админки без входа в счёт не идут."""
    async with visitor() as c:
        for _ in range(6):
            await c.get("/admin/login")
            await c.get("/admin/product/list")
        assert await failures_of(c.ip) == 0
        assert (await login(c, PASSWORD)).status_code == 302


async def test_unknown_address_is_one_shared_address(monkeypatch):
    """003:FR-001: адрес неизвестен — все такие запросы считаются как один общий адрес."""
    import app.admin.auth as auth

    monkeypatch.setattr(auth, "client_ip", lambda request: "unknown")
    async with visitor() as first, visitor() as second:
        await fail(first, 5)
        assert (await login(second, PASSWORD)).status_code != 302
        assert await failures_of("unknown") == 5
    async with SessionLocal() as s:  # убрать за собой общий «unknown»
        model = failure_model()
        await s.execute(
            model.__table__.delete().where(model.client_hash == client_fingerprint("unknown", settings.secret_key))
        )
        await s.commit()


async def test_successful_login_resets_failures():
    """003:FR-004: удачный вход обнуляет счёт адреса — 4 ошибки, вход, ещё 4 ошибки, вход снова работает."""
    async with visitor() as c:
        await fail(c, 4)
        assert (await login(c, PASSWORD)).status_code == 302
        await c.get("/admin/logout")
        await fail(c, 4)
        assert (await login(c, PASSWORD)).status_code == 302


async def test_blocked_sees_too_many_attempts_message(monkeypatch):
    """003:FR-005: заблокированный видит «Слишком много попыток…», а не ошибку пароля; минуты — из настройки."""
    async with visitor() as c:
        first = await login(c)
        assert INVALID in first.text and BLOCKED not in first.text
        await fail(c, 4)
        r = await login(c, PASSWORD)
        assert BLOCKED in r.text
        assert INVALID not in r.text
    monkeypatch.setattr(settings, "admin_login_limit_minutes", 30, raising=False)
    async with visitor() as c:
        await fail(c, 5)
        assert "Слишком много попыток, попробуйте через 30 минут" in (await login(c)).text


async def test_blocked_gets_429():
    """003:FR-006: ответ с закрытого адреса — 429; неверный пароль с открытого — 400, как раньше."""
    async with visitor() as c:
        assert await fail(c, 5) == [400] * 5
        assert (await login(c, PASSWORD)).status_code == 429


async def test_failures_from_other_copy_count():
    """003:FR-007: ошибки, записанные другой копией сайта или до перезапуска, идут в счёт."""
    async with visitor() as c:
        await add_failures(c.ip, 5)
        assert (await login(c, PASSWORD)).status_code != 302


async def test_simultaneous_failures_are_not_lost():
    """003:FR-007: 10 одновременных неверных попыток — записано не больше 5, шестая и дальше не прошли."""
    async with visitor() as c:
        await asyncio.gather(*(login(c) for _ in range(10)))
        assert await failures_of(c.ip) == 5


async def test_only_fingerprint_is_stored():
    """003:FR-008: в таблице попыток — отпечаток вместо адреса, без введённых логина и пароля."""
    model = failure_model()
    async with visitor() as c:
        await login(c, password="secret-typo-9182", username="boss-login")
        async with SessionLocal() as s:
            rows = (await s.execute(select(model.__table__))).mappings().all()
    stored = " ".join(str(v) for row in rows for v in row.values())
    assert client_fingerprint(c.ip, settings.secret_key) in stored
    assert c.ip not in stored
    assert "secret-typo-9182" not in stored and "boss-login" not in stored


async def test_old_failures_are_deleted():
    """003:FR-009: записи старше 15 минут удаляются при любой попытке входа — даже чужого адреса."""
    old_ip = f"198.51.100.{next(_addresses)}"
    await add_failures(old_ip, 3, minutes_ago=16)
    async with visitor() as c:
        await login(c)
    assert await failures_of(old_ip) == 0


async def test_block_is_logged_without_address_and_credentials(caplog):
    """003:FR-010: блокировка — предупреждение в журнале с отпечатком; без адреса, логина и пароля."""
    async with visitor() as c:
        await fail(c, 5)
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            await login(c, password="secret-typo-4410", username="boss-login")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(client_fingerprint(c.ip, settings.secret_key) in r.getMessage() for r in warnings)
    assert c.ip not in caplog.text
    assert "secret-typo-4410" not in caplog.text and "boss-login" not in caplog.text


def test_login_failures_migration_upgrades_and_downgrades(migrations_db):
    """003:FR-007: счёт хранится в базе — таблицу создаёт миграция, откат и повтор работают."""
    from sqlalchemy import inspect

    from tests.helpers import run_alembic

    def tables() -> set[str]:
        migrations_db.dispose()
        return set(inspect(migrations_db).get_table_names())

    run_alembic("upgrade", "head")
    assert "admin_login_failures" in tables()
    run_alembic("downgrade", "0007")
    assert "admin_login_failures" not in tables()
    run_alembic("upgrade", "head")
    assert "admin_login_failures" in tables()
