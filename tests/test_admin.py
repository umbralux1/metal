"""Админка: вход, создание и переименование с редиректами, валидация, заявки."""

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.admin.auth import reset_login_limits
from app.catalog.models import Category, FilterLanding, Product, Redirect
from app.core.config import settings
from app.core.db import SessionLocal
from app.leads.models import Lead
from app.main import app as fastapi_app
from app.main import create_app

ADMIN_PAGES = ["category", "product", "price", "filter-landing", "redirect", "lead"]


def new_client(app=fastapi_app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


@pytest_asyncio.fixture
async def admin():
    reset_login_limits()
    async with new_client() as c:
        r = await c.post("/admin/login", data={"username": "admin", "password": "test-admin-pass"})
        assert r.status_code == 302
        yield c


async def get_one(model, **filters):
    async with SessionLocal() as s:
        return await s.scalar(select(model).filter_by(**filters))


async def test_admin_requires_login():
    async with new_client() as c:
        r = await c.get("/admin/product/list")
        assert r.status_code in (302, 303)
        assert "/admin/login" in r.headers["location"]


async def test_wrong_password_and_brute_force_block():
    reset_login_limits()
    async with new_client() as c:
        for _ in range(5):
            r = await c.post("/admin/login", data={"username": "admin", "password": "nope"})
            assert r.status_code != 302
        # После 5 ошибок не пускает даже с верным паролем
        r = await c.post("/admin/login", data={"username": "admin", "password": "test-admin-pass"})
        assert r.status_code != 302
    reset_login_limits()


@pytest.mark.parametrize("page", ADMIN_PAGES)
async def test_admin_list_pages(admin, page):
    r = await admin.get(f"/admin/{page}/list")
    assert r.status_code == 200


async def test_admin_disabled_without_password(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "")
    async with new_client(create_app()) as c:
        assert (await c.get("/admin/login")).status_code == 404


async def test_robots_hides_admin(client):
    assert "Disallow: /admin/" in (await client.get("/robots.txt")).text


async def test_create_category_product_and_rename_with_redirects(admin):
    # Новый раздел: slug и путь собираются из названия
    r = await admin.post(
        "/admin/category/create", data={"name": "Уголок стальной", "slug": "", "sort": "30", "is_active": "y"}
    )
    assert r.status_code == 302, r.text[:500]
    cat = await get_one(Category, name="Уголок стальной")
    assert (cat.slug, cat.path) == ("ugolok-stalnoy", "ugolok-stalnoy")

    r = await admin.post(
        "/admin/product/create",
        data={
            "name": "Уголок 50х50х5",
            "slug": "",
            "category": str(cat.id),
            "steel_grade": "Ст3",
            "gost": "ГОСТ 8509-93",
            "length_m": "6",
            "weight_per_m_kg": "3.77",
            "base_unit": "m",
            "in_stock": "y",
            "is_active": "y",
            "attrs": '{"profile": "angle"}',
        },
    )
    assert r.status_code == 302, r.text[:500]
    product = await get_one(Product, name="Уголок 50х50х5")
    assert product.path == "ugolok-stalnoy/ugolok-50x50x5"
    assert product.search_text == "уголок 50x50x5 ст3 гост 8509 93"

    r = await admin.post(
        "/admin/filter-landing/create",
        data={
            "name": "Уголок 50х50",
            "slug": "50x50",
            "category": str(cat.id),
            "filters": '{"width_mm": 50, "height_mm": 50}',
            "is_indexable": "y",
            "sort": "0",
        },
    )
    assert r.status_code == 302, r.text[:500]

    # Переименовали раздел: меняются адреса всего внутри и появляются 301 со старых адресов
    r = await admin.post(
        f"/admin/category/edit/{cat.id}", data={"name": "Уголок", "slug": "ugolok", "sort": "30", "is_active": "y"}
    )
    assert r.status_code == 302, r.text[:500]
    product = await get_one(Product, id=product.id)
    # Раздел попал под правило «Уголок»: slug товара стал коротким, как у остальных товаров с размером
    assert product.path == "ugolok/50x50x5"
    landing = await get_one(FilterLanding, name="Уголок 50х50")
    assert landing.path == "ugolok/50x50"

    async with new_client() as site:
        for old, new in [
            ("/catalog/ugolok-stalnoy/", "/catalog/ugolok/"),
            ("/catalog/ugolok-stalnoy/ugolok-50x50x5/", "/catalog/ugolok/50x50x5/"),
            ("/catalog/ugolok-stalnoy/50x50/", "/catalog/ugolok/50x50/"),
        ]:
            r = await site.get(old)
            assert (r.status_code, r.headers["location"]) == (301, new)
        assert (await site.get("/catalog/ugolok/50x50x5/")).status_code == 200

    # Выключили товар — его адрес ведёт в раздел, а не в 404
    r = await admin.post(
        f"/admin/product/edit/{product.id}",
        data={
            "name": "Уголок 50х50х5",
            "slug": "ugolok-50x50x5",
            "category": str(cat.id),
            "base_unit": "m",
            "attrs": "{}",
            "in_stock": "y",
        },
    )
    assert r.status_code == 302, r.text[:500]
    async with new_client() as site:
        r = await site.get("/catalog/ugolok/ugolok-50x50x5/")
        assert (r.status_code, r.headers["location"]) == (301, "/catalog/ugolok/")


async def test_rename_back_does_not_leave_loop(admin):
    r = await admin.post(
        "/admin/category/create", data={"name": "Квадрат", "slug": "kvadrat", "sort": "0", "is_active": "y"}
    )
    assert r.status_code == 302
    cat = await get_one(Category, path="kvadrat")
    for slug in ("kvadrat-stalnoy", "kvadrat"):
        r = await admin.post(
            f"/admin/category/edit/{cat.id}", data={"name": "Квадрат", "slug": slug, "sort": "0", "is_active": "y"}
        )
        assert r.status_code == 302
    assert await get_one(Redirect, from_path="/catalog/kvadrat/") is None
    redirect = await get_one(Redirect, from_path="/catalog/kvadrat-stalnoy/")
    assert redirect.to_path == "/catalog/kvadrat/"


async def test_duplicate_address_is_rejected(admin):
    armatura = await get_one(Category, path="armatura")
    # Посадочная с адресом существующего подраздела «armatura/a500c» — нельзя
    r = await admin.post(
        "/admin/filter-landing/create",
        data={
            "name": "Дубль",
            "slug": "a500c",
            "category": str(armatura.id),
            "filters": '{"diameter_mm": 12}',
            "sort": "0",
        },
    )
    assert r.status_code == 400
    assert "уже занят" in r.text


async def test_landing_filter_validation(admin):
    armatura = await get_one(Category, path="armatura")
    r = await admin.post(
        "/admin/filter-landing/create",
        data={
            "name": "Арматура красная",
            "slug": "",
            "category": str(armatura.id),
            "filters": '{"color": "red"}',
            "sort": "0",
        },
    )
    assert r.status_code == 400
    assert "Неизвестные ключи фильтра" in r.text


async def test_redirect_paths_are_normalized(admin):
    r = await admin.post(
        "/admin/redirect/create", data={"from_path": "Old-Page", "to_path": "catalog/armatura", "status_code": "301"}
    )
    assert r.status_code == 302, r.text[:500]
    redirect = await get_one(Redirect, from_path="/old-page/")
    assert redirect.to_path == "/catalog/armatura/"


async def test_lead_status_change(admin):
    async with SessionLocal() as s:
        lead = Lead(product_name="Арматура", phone="+79161234567", calc={"total_kop": 50603})
        s.add(lead)
        await s.commit()
        lead_id = lead.id
    r = await admin.get("/admin/lead/list")
    assert "506,03" in r.text
    r = await admin.post(f"/admin/lead/edit/{lead_id}", data={"status": "in_progress", "comment": "перезвонил"})
    assert r.status_code == 302, r.text[:500]
    lead = await get_one(Lead, id=lead_id)
    assert (lead.status, lead.comment) == ("in_progress", "перезвонил")


async def test_generate_landings_action_and_manual_edit(admin):
    r = await admin.get("/admin/filter-landing/action/generate?pks=")
    assert r.status_code == 302 and r.headers["location"].endswith("/admin/filter-landing/list")
    landing = await get_one(FilterLanding, path="truba-profilnaya/kvadratnaya/40x40")
    assert landing.is_generated

    # Поправили посадочную руками — она становится ручной, генератор её больше не перезапишет
    r = await admin.post(
        f"/admin/filter-landing/edit/{landing.id}",
        data={
            "name": landing.name,
            "slug": "40x40",
            "category": str(landing.category_id),
            "filters": '{"width_mm": 40, "height_mm": 40}',
            "is_indexable": "y",
            "sort": str(landing.sort),
            "h1": "Труба 40х40 — своя H1",
            "title": "Своя труба 40х40 {price}",
        },
    )
    assert r.status_code == 302, r.text[:500]
    assert not (await get_one(FilterLanding, id=landing.id)).is_generated
    await admin.get("/admin/filter-landing/action/generate?pks=")
    landing = await get_one(FilterLanding, id=landing.id)
    assert landing.h1 == "Труба 40х40 — своя H1" and not landing.is_generated
    async with new_client() as site:
        html = (await site.get("/catalog/truba-profilnaya/kvadratnaya/40x40/")).text
    assert "<title>Своя труба 40х40 от 195\u00a0₽</title>" in html
