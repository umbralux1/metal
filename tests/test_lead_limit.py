"""Ограничение частоты заявок: не больше 5 заявок за 10 минут с одного адреса (specs/001-lead-rate-limit).

Порог здесь настоящий (в остальных тестах его поднимает фикстура в conftest.py). У каждого теста свой адрес
подключения — тесты не мешают друг другу.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from itertools import count

import httpx
from sqlalchemy import func, select, update

from app.catalog.models import Product
from app.core.config import settings
from app.core.db import SessionLocal
from app.leads.models import Lead
from app.main import app as fastapi_app

FETCH = {"X-Requested-With": "fetch"}
TOO_MANY = "Слишком много заявок"
_addresses = count(10)


@asynccontextmanager
async def buyer(ip: str | None = None):
    """Покупатель со своим адресом подключения и своими cookie."""
    ip = ip or f"203.0.113.{next(_addresses)}"
    transport = httpx.ASGITransport(app=fastapi_app, client=(ip, 51000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        c.ip = ip  # type: ignore[attr-defined]
        yield c


async def product_id() -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(Product.id).where(Product.path == "armatura/12-mm/12-mm-a500s"))


async def lead_ids() -> set[int]:
    async with SessionLocal() as s:
        return set(await s.scalars(select(Lead.id)))


def lead_form(pid: int, **extra) -> dict:
    return {"product_id": pid, "unit": "pcs", "qty": "1", "phone": "+7 916 123-45-67", "name": "Иван", **extra}


async def send_leads(c: httpx.AsyncClient, n: int) -> list[int]:
    pid = await product_id()
    return [(await c.post("/api/lead/", data=lead_form(pid), headers=FETCH)).status_code for _ in range(n)]


async def checkout(c: httpx.AsyncClient, **extra) -> httpx.Response:
    await c.post("/cart/add/", data={"product_id": await product_id(), "unit": "pcs", "qty": "1"})
    return await c.post("/cart/checkout/", data={"phone": "+7 916 123-45-67", "delivery": "pickup", **extra})


async def test_five_leads_accepted_sixth_rejected():
    """001:FR-001: с одного адреса принимается 5 заявок за 10 минут, шестая — нет."""
    async with buyer() as c:
        before = await lead_ids()
        assert await send_leads(c, 5) == [200] * 5
        sixth = await c.post("/api/lead/", data=lead_form(await product_id()), headers=FETCH)
        assert TOO_MANY in sixth.text
        assert len(await lead_ids() - before) == 5


async def test_product_leads_and_cart_orders_share_the_limit():
    """001:FR-001: заявки с карточки и заказы из корзины считаются вместе."""
    async with buyer() as c:
        before = await lead_ids()
        assert await send_leads(c, 3) == [200] * 3
        assert (await checkout(c)).status_code == 200
        assert (await checkout(c)).status_code == 200
        r = await c.post("/api/lead/", data=lead_form(await product_id()), headers=FETCH)
        assert TOO_MANY in r.text
        assert len(await lead_ids() - before) == 5


async def test_rejected_lead_is_not_saved_and_manager_is_not_notified(monkeypatch):
    """001:FR-002: заявка сверх порога не сохраняется, менеджер о ней не уведомляется."""
    notified = []

    async def fake_notify(lead):
        notified.append(lead.id)

    monkeypatch.setattr("app.leads.service.notify_new_lead", fake_notify)
    async with buyer() as c:
        await send_leads(c, 5)
        assert len(notified) == 5
        before = await lead_ids()
        await send_leads(c, 1)
        await checkout(c)
        assert await lead_ids() == before
        assert len(notified) == 5


async def test_form_errors_and_honeypot_do_not_count():
    """001:FR-003: заявки с ошибками в форме и пойманные ловушкой в счёт порога не идут."""
    async with buyer() as c:
        pid = await product_id()
        await c.post("/cart/add/", data={"product_id": pid, "unit": "pcs", "qty": "1"})
        for _ in range(5):
            assert (await c.post("/api/lead/", data=lead_form(pid, phone="123"), headers=FETCH)).status_code == 422
            await c.post("/api/lead/", data=lead_form(pid, website="spam.example"), headers=FETCH)
            assert (await c.post("/cart/checkout/", data={"phone": "123", "delivery": "pickup"})).status_code == 422
        assert await send_leads(c, 5) == [200] * 5


async def test_limit_ends_after_window_and_does_not_touch_other_addresses():
    """001:FR-004: заявки старше 10 минут не считаются; порог одного адреса не мешает другим."""
    async with buyer() as c:
        before = await lead_ids()
        await send_leads(c, 5)
        async with buyer() as other:
            assert await send_leads(other, 1) == [200]
        assert TOO_MANY in (await c.post("/api/lead/", data=lead_form(await product_id()), headers=FETCH)).text

        mine = await lead_ids() - before
        async with SessionLocal() as s:
            await s.execute(
                update(Lead)
                .where(Lead.id.in_(mine))
                .values(created_at=func.now() - func.make_interval(0, 0, 0, 0, 0, 11))
            )
            await s.commit()
        assert await send_leads(c, 1) == [200]


async def test_rejected_product_lead_shows_phone_and_keeps_input():
    """001:FR-005: сверх порога с карточки — сообщение с телефоном магазина, введённое осталось в форме."""
    async with buyer() as c:
        await send_leads(c, 5)
        data = lead_form(await product_id(), qty="7", phone="+7 916 765-43-21", name="Ира", comment="Подольск")
        for headers in (FETCH, {}):
            r = await c.post("/api/lead/", data=data, headers=headers)
            assert TOO_MANY in r.text
            assert settings.phone in r.text
            for value in ('value="+7 916 765-43-21"', 'value="Ира"', 'value="Подольск"', 'name="qty" value="7"'):
                assert value in r.text


async def test_rejected_cart_order_shows_phone_and_keeps_cart_and_input():
    """001:FR-006: сверх порога в корзине — то же сообщение, корзина и введённые данные на месте."""
    async with buyer() as c:
        await send_leads(c, 5)
        r = await checkout(c, phone="+7 916 765-43-21", name="Ира")
        assert TOO_MANY in r.text
        assert settings.phone in r.text
        assert 'value="+7 916 765-43-21"' in r.text and 'value="Ира"' in r.text
        cart = await c.get("/cart/")
        assert "В корзине пока ничего нет" not in cart.text
        assert "12 мм" in cart.text


async def test_rejected_requests_answer_429():
    """001:FR-007: ответ на заявку сверх порога — 429 «слишком много запросов», у обеих форм."""
    async with buyer() as c:
        await send_leads(c, 5)
        assert await send_leads(c, 1) == [429]
        assert (await c.post("/api/lead/", data=lead_form(await product_id()))).status_code == 429
        assert (await checkout(c)).status_code == 429


async def test_rejected_lead_name_and_phone_are_not_logged(caplog, monkeypatch):
    """001:FR-008: имя и телефон из отклонённой заявки не попадают в журнал."""
    # Тесты миграций настраивают журнал заново (fileConfig) и выключают логгеры сайта — включаем их на время теста
    for logger in logging.root.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            monkeypatch.setattr(logger, "disabled", False)
    async with buyer() as c:
        await send_leads(c, 5)
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            pid = await product_id()
            await c.post("/api/lead/", data=lead_form(pid, phone="+7 916 555-00-08", name="Отклонённый"), headers=FETCH)
            await checkout(c, phone="+7 916 555-00-08", name="Отклонённый")
        assert "5550008" not in caplog.text and "555-00-08" not in caplog.text
        assert "Отклонённый" not in caplog.text


async def test_limit_counts_leads_saved_by_other_site_copies():
    """001:FR-009: счёт общий для копий сайта — заявки, сохранённые другой копией, идут в счёт."""
    from app.leads.fingerprint import client_fingerprint

    async with buyer() as c:
        fingerprint = client_fingerprint(c.ip, settings.secret_key)
        async with SessionLocal() as s:
            for _ in range(5):
                s.add(Lead(product_name="Другая копия", phone="+79160000000", client_hash=fingerprint))
            await s.commit()
        assert await send_leads(c, 1) == [429]


async def test_simultaneous_leads_do_not_slip_through():
    """001:FR-009: 10 одновременных заявок с одного адреса — сохраняется ровно 5."""
    async with buyer() as c:
        before = await lead_ids()
        pid = await product_id()
        responses = await asyncio.gather(*(c.post("/api/lead/", data=lead_form(pid), headers=FETCH) for _ in range(10)))
        assert sorted(r.status_code for r in responses) == [200] * 5 + [429] * 5
        assert len(await lead_ids() - before) == 5


async def test_address_is_stored_only_as_fingerprint():
    """001:FR-010: адрес хранится только отпечатком — по нему видно «тот же адрес», но адреса в нём нет."""
    from app.leads.fingerprint import client_fingerprint

    async with buyer("198.51.100.77") as c:
        before = await lead_ids()
        await send_leads(c, 1)
        async with SessionLocal() as s:
            lead = await s.get(Lead, (await lead_ids() - before).pop())
    assert lead.client_hash == client_fingerprint("198.51.100.77", settings.secret_key)
    assert "198.51.100.77" not in lead.client_hash
    assert "198.51.100.77" not in str(lead.calc) and "198.51.100.77" not in lead.comment

    assert client_fingerprint("198.51.100.77", "key-a") == client_fingerprint("198.51.100.77", "key-a")
    assert client_fingerprint("198.51.100.77", "key-a") != client_fingerprint("198.51.100.78", "key-a")
    assert client_fingerprint("198.51.100.77", "key-a") != client_fingerprint("198.51.100.77", "key-b")


def test_site_on_host_does_not_start_without_secret_key():
    """001:FR-009: без SECRET_KEY у каждой копии свой ключ и свой счёт — на хостинге такой сайт не запускается."""
    import pytest

    from main import check_host_env

    with pytest.raises(SystemExit, match="SECRET_KEY"):
        check_host_env({"PORT": "10000"})
    check_host_env({"PORT": "10000", "SECRET_KEY": "x" * 32})
    check_host_env({})  # локально ключ необязателен


def test_client_hash_migration_upgrades_and_downgrades(migrations_db):
    """001:FR-009: счёт хранится в базе — поле отпечатка и индекс создаются миграцией, откат и повтор работают."""
    from sqlalchemy import inspect

    from tests.helpers import run_alembic

    def columns() -> set[str]:
        migrations_db.dispose()
        return {c["name"] for c in inspect(migrations_db).get_columns("leads")}

    run_alembic("upgrade", "head")
    assert "client_hash" in columns()
    assert "ix_leads_client_hash_created_at" in {i["name"] for i in inspect(migrations_db).get_indexes("leads")}
    run_alembic("downgrade", "0006")
    assert "client_hash" not in columns()
    run_alembic("upgrade", "head")
    assert "client_hash" in columns()
