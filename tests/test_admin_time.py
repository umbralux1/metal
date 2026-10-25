"""Время в админке — в часовом поясе сайта (по умолчанию Москва), а не в UTC.

В базе время хранится с поясом (`timestamptz`), база на Render и в docker-compose отдаёт его в UTC. Без перевода
заявка, пришедшая в 10:05 по Москве, показывалась менеджеру как 07:05.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import delete

from app.catalog.models import Redirect
from app.core.config import Settings, settings
from app.core.db import SessionLocal
from app.core.templating import site_year
from app.leads.models import Lead

# Вечер по UTC — уже следующий день по Москве: тест ловит и часы, и дату, оставшиеся по UTC.
# Год в будущем — чтобы запись была первой в списках, отсортированных от новых к старым.
MOMENT = datetime(2030, 1, 14, 22, 30, tzinfo=UTC)
MOSCOW_TEXT = "15.01.2030 01:30"  # 22:30 UTC + 3 часа (летнего времени в России нет с 2014 года)
UTC_TEXT = "14.01.2030 22:30"
REDIRECT_FROM = "/time-test-old/"


@pytest.fixture
def moscow(monkeypatch):
    """Пояс задаём явно: проверки показа не зависят от TIMEZONE в .env разработчика."""
    monkeypatch.setattr(settings, "timezone", "Europe/Moscow")


@pytest_asyncio.fixture
async def lead_id(moscow):
    async with SessionLocal() as s:
        lead = Lead(product_name="Проверка времени", phone="+79161234567", calc={}, created_at=MOMENT)
        s.add(lead)
        await s.commit()
        yield lead.id
        await s.execute(delete(Lead).where(Lead.id == lead.id))
        await s.commit()


@pytest_asyncio.fixture
async def redirect(moscow):
    async with SessionLocal() as s:
        s.add(Redirect(from_path=REDIRECT_FROM, to_path="/catalog/", created_at=MOMENT))
        await s.commit()
        yield
        await s.execute(delete(Redirect).where(Redirect.from_path == REDIRECT_FROM))
        await s.commit()


# ---------- Настройка ----------


def test_site_timezone_is_moscow_by_default():
    assert Settings.model_fields["timezone"].default == "Europe/Moscow"


def test_unknown_timezone_stops_startup():
    """Опечатка в TIMEZONE на Render — понятная ошибка при запуске, а не падение админки на заявках."""
    with pytest.raises(ValidationError, match="timezone"):
        Settings(timezone="Europe/Moskow")


# ---------- Показ в админке ----------


async def test_lead_list_shows_moscow_time(admin, lead_id):
    html = (await admin.get("/admin/lead/list")).text
    assert MOSCOW_TEXT in html
    assert UTC_TEXT not in html


async def test_lead_details_show_moscow_time(admin, lead_id):
    html = (await admin.get(f"/admin/lead/details/{lead_id}")).text
    assert MOSCOW_TEXT in html
    assert UTC_TEXT not in html


async def test_redirect_list_shows_moscow_time(admin, redirect):
    html = (await admin.get("/admin/redirect/list")).text
    assert MOSCOW_TEXT in html
    assert UTC_TEXT not in html


async def test_time_follows_timezone_setting(admin, lead_id, monkeypatch):
    monkeypatch.setattr(settings, "timezone", "Asia/Yekaterinburg")  # UTC+5
    html = (await admin.get(f"/admin/lead/details/{lead_id}")).text
    assert "15.01.2030 03:30" in html


def test_footer_year_follows_site_timezone(moscow):
    """Год в подвале — по часовому поясу сайта: в новогоднюю ночь в UTC ещё 31 декабря, а по Москве уже 2027."""
    assert site_year(datetime(2026, 12, 31, 21, 30, tzinfo=UTC)) == 2027
