"""Ошибки корзины, найденные при сверке спецификации (specs/002-cart-checkout): BUG-009…014."""

import re

import httpx
import pytest_asyncio
from sqlalchemy import delete, select

from app.catalog.models import Category, Price, Product, Unit
from app.core.db import SessionLocal
from app.leads.models import Lead
from app.main import app as fastapi_app

FETCH = {"X-Requested-With": "fetch"}
TUBE = "truba-profilnaya/kvadratnaya/40x40/40x40x2"


@pytest_asyncio.fixture
async def shop():
    """Отдельный покупатель со своей корзиной."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fastapi_app), base_url="http://testserver") as c:
        yield c


async def pid(path: str = "armatura/12-mm/12-mm-a500s") -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(Product.id).where(Product.path == path))


def cut(product_id: int, length: str, count: str = "10") -> dict:
    return {"product_id": product_id, "unit": "m", "cut": "1", "cut_len": length, "cut_count": count}


async def last_lead() -> Lead:
    async with SessionLocal() as s:
        return await s.scalar(select(Lead).order_by(Lead.id.desc()).limit(1))


async def test_same_cut_added_twice_merges_into_one_line(shop):
    """BUG-009, 002:FR-003: та же резка дважды — одна строка с суммой отрезков; другая длина — отдельная строка."""
    rebar = await pid()
    first = await shop.post("/cart/add/", data=cut(rebar, "3,9"), headers=FETCH)
    second = await shop.post("/cart/add/", data=cut(rebar, "3,9"), headers=FETCH)
    assert first.json()["count"] == 1 and second.json()["count"] == 1
    page = (await shop.get("/cart/")).text
    assert "резка 20 × 3,9 м" in page and "резка 10 × 3,9 м" not in page

    other = await shop.post("/cart/add/", data=cut(rebar, "2"), headers=FETCH)
    assert other.json()["count"] == 2


async def test_without_js_bad_quantity_returns_to_product_with_error(shop):
    """BUG-010, 002:FR-004: без JavaScript неверное количество — карточка с введёнными данными и ошибкой."""
    r = await shop.post("/cart/add/", data={"product_id": await pid(), "unit": "m", "qty": "0"})
    assert r.status_code == 303
    location = r.headers["location"]
    assert "/catalog/armatura/12-mm/12-mm-a500s/" in location and "qty=0" in location
    page = await shop.get(location.split("#")[0])
    assert 'class="calc-error"' in page.text or "calc-error" in page.text


async def test_without_js_full_cart_shows_message_in_cart(shop):
    """BUG-010, 002:FR-004, 002:FR-008: без JavaScript 31-я позиция — корзина с сообщением про 30 позиций."""
    rebar = await pid()
    for i in range(30):
        await shop.post("/cart/add/", data=cut(rebar, f"1,{i:02d}", "1"))
    r = await shop.post("/cart/add/", data=cut(rebar, "5,55", "1"))
    assert r.status_code == 303 and r.headers["location"].startswith("/cart/")
    page = (await shop.get(r.headers["location"])).text
    assert "30 позиций" in page
    assert page.count('<article class="cart-line') == 30


async def test_merge_over_max_quantity_is_rejected(shop):
    """BUG-011, 002:FR-004: склейка сверх допустимого количества не выполняется, корзина не меняется."""
    data = {"product_id": await pid(), "unit": "m", "qty": "60000"}
    assert (await shop.post("/cart/add/", data=data, headers=FETCH)).json()["ok"]
    second = await shop.post("/cart/add/", data=data, headers=FETCH)
    assert second.status_code == 422 and second.json()["ok"] is False
    assert "Слишком большое количество" in second.json()["error"]
    page = (await shop.get("/cart/")).text
    assert 'value="60000"' in page and "Слишком большое количество" not in page


async def test_negative_index_does_not_change_cart(shop):
    """BUG-012, 002:FR-007: изменение и удаление позиции «-1» корзину не меняют."""
    await shop.post("/cart/add/", data={"product_id": await pid(), "unit": "m", "qty": "11,7"})
    await shop.post("/cart/add/", data={"product_id": await pid(TUBE), "unit": "m", "qty": "6"})
    await shop.post("/cart/update/", data={"index": "-1", "qty": "1"})
    await shop.post("/cart/remove/", data={"index": "-1"})
    page = (await shop.get("/cart/")).text
    assert page.count('<article class="cart-line') == 2
    assert 'value="6"' in page


async def test_distance_is_kept_when_no_vehicle_fits(shop):
    """BUG-013, 002:FR-015: доставка, которую не увезёт ни одна машина, — расстояние в заказе и в админке."""
    from app.admin.leads import _lead_calc_html

    await shop.post("/cart/add/", data={"product_id": await pid(), "unit": "m", "qty": "40000"})
    order = {
        "phone": "+7 916 123-45-67",
        "delivery": "delivery",
        "address": "Подольск, ул. Мира, 5",
        "distance_km": "18",
    }
    assert (await shop.post("/cart/checkout/", data=order)).status_code == 200
    lead = await last_lead()
    assert lead.calc["vehicle"] is None
    assert lead.calc["distance_km"] == "18"
    assert "18 км" in str(_lead_calc_html(lead.calc))


@pytest_asyncio.fixture
async def retired_product():
    """Товар, который положили в корзину, а потом сняли с продажи."""
    async with SessionLocal() as s:
        category = await s.scalar(select(Category).where(Category.path == "armatura"))
        product = Product(
            category_id=category.id, slug="test-retired", path="armatura/test-retired", name="Снятый товар",
            base_unit=Unit.PIECE, prices=[Price(unit=Unit.PIECE, amount_kop=5000)],
        )  # fmt: skip
        s.add(product)
        await s.commit()
        yield product
        await s.execute(delete(Product).where(Product.id == product.id))
        await s.commit()


async def deactivate(product: Product) -> None:
    async with SessionLocal() as s:
        (await s.get(Product, product.id)).is_active = False
        await s.commit()


async def test_retired_product_has_no_quantity_form(shop, retired_product):
    """BUG-014, 002:FR-006: у снятого с продажи товара только сообщение и удаление, заказ не оформить."""
    await shop.post("/cart/add/", data={"product_id": retired_product.id, "unit": "pcs", "qty": "3"})
    await deactivate(retired_product)
    page = (await shop.get("/cart/")).text
    assert "Товар больше не продаётся" in page
    assert not re.search(r'name="qty"[^>]*value="3"', page)
    assert 'action="/cart/remove/"' in page
    r = await shop.post("/cart/checkout/", data={"phone": "+7 916 123-45-67", "delivery": "pickup"})
    assert r.status_code == 422 and "Исправьте позиции" in r.text
