"""Корзина: добавление, пересчёт по текущим ценам, удаление, оформление заказа."""

import re

import httpx
import pytest_asyncio
from sqlalchemy import select

from app.cart.store import COOKIE
from app.catalog.models import Product
from app.core.db import SessionLocal
from app.delivery.models import DeliveryVehicle
from app.leads.models import Lead
from app.main import app as fastapi_app

REBAR = "/catalog/armatura/12-mm/12-mm-a500s/"


@pytest_asyncio.fixture
async def shop():
    """Отдельный клиент со своими cookie — как отдельный покупатель."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fastapi_app), base_url="http://testserver") as c:
        yield c


async def _pid(path: str) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(Product.id).where(Product.path == path.strip("/").removeprefix("catalog/")))


async def test_empty_cart_is_noindex(shop):
    """002:FR-010: страница корзины не индексируется."""
    r = await shop.get("/cart/")
    assert r.status_code == 200 and "В корзине пока ничего нет" in r.text
    assert r.headers["x-robots-tag"].startswith("noindex")


async def test_add_without_js_redirects_to_cart_and_counts(shop):
    """002:FR-001, 002:FR-002, 002:FR-005: без JavaScript — в корзину, цена по текущей, счётчик в шапке."""
    pid = await _pid(REBAR)
    r = await shop.post("/cart/add/", data={"product_id": pid, "unit": "m", "qty": "11,7"})
    assert r.status_code == 303 and r.headers["location"] == "/cart/"
    page = (await shop.get("/cart/")).text
    assert "Арматура 12 мм А500С" in page and "506,03" in page  # 1 пруток × 43,25 ₽/м
    # Счётчик в шапке на любой странице
    assert re.search(r"data-cart-count\s*>1<", (await shop.get("/contacts/")).text)


async def test_add_with_fetch_returns_count_and_merges_same_item(shop):
    """002:FR-002, 002:FR-003: что добавлено и сколько; та же позиция складывается."""
    pid = await _pid(REBAR)
    headers = {"X-Requested-With": "fetch"}
    r1 = await shop.post("/cart/add/", data={"product_id": pid, "unit": "m", "qty": "11,7"}, headers=headers)
    r2 = await shop.post("/cart/add/", data={"product_id": pid, "unit": "m", "qty": "11,7"}, headers=headers)
    assert r1.json()["count"] == 1 and r2.json()["count"] == 1  # та же позиция — количество сложилось
    # Для уведомления «Добавлено в корзину»: что, сколько и на какую сумму
    added = r1.json()
    assert added["name"] and "11,7 м" in added["summary"] and added["total"].endswith("₽")
    page = (await shop.get("/cart/")).text
    assert 'value="23,4"' in page and "1\u00a0012,05" in page


async def test_cart_line_with_cutting_and_bad_quantity(shop):
    """002:FR-004: позиция, которая не считается, в корзину не кладётся; резка — своя строка."""
    pid = await _pid(REBAR)
    headers = {"X-Requested-With": "fetch"}
    bad = await shop.post("/cart/add/", data={"product_id": pid, "unit": "m", "qty": "0"}, headers=headers)
    assert bad.status_code == 422 and bad.json()["ok"] is False
    cut = {"product_id": pid, "unit": "m", "cut": "1", "cut_len": "3,9", "cut_count": "10"}
    assert (await shop.post("/cart/add/", data=cut, headers=headers)).json()["ok"]
    page = (await shop.get("/cart/")).text
    assert "резка 10 × 3,9 м" in page and "2\u00a0374,10" in page


async def test_update_and_remove(shop):
    """002:FR-007: изменить количество и удалить позицию."""
    pid = await _pid(REBAR)
    await shop.post("/cart/add/", data={"product_id": pid, "unit": "m", "qty": "11,7"})
    await shop.post("/cart/update/", data={"index": 0, "qty": "23,4"})
    assert "1\u00a0012,05" in (await shop.get("/cart/")).text
    await shop.post("/cart/remove/", data={"index": 0})
    assert "В корзине пока ничего нет" in (await shop.get("/cart/")).text


async def test_tampered_cookie_gives_empty_cart(shop):
    """002:FR-009: подделанная корзина — пустая."""
    shop.cookies.set(COOKIE, "forged.value")
    assert "В корзине пока ничего нет" in (await shop.get("/cart/")).text


async def test_checkout_creates_order_with_items_and_clears_cart(shop):
    """002:FR-011, 002:FR-012, 002:FR-015, 002:FR-016: телефон, адрес, снимок заказа, корзина очищена."""
    rebar, tube = await _pid(REBAR), await _pid("/catalog/truba-profilnaya/kvadratnaya/40x40/40x40x2/")
    await shop.post("/cart/add/", data={"product_id": rebar, "unit": "m", "qty": "11,7"})
    await shop.post("/cart/add/", data={"product_id": tube, "unit": "m", "qty": "6"})

    no_address = await shop.post("/cart/checkout/", data={"phone": "+7 916 123-45-67", "delivery": "delivery"})
    assert no_address.status_code == 422 and "Укажите адрес доставки" in no_address.text
    bad_phone = await shop.post("/cart/checkout/", data={"phone": "123", "delivery": "pickup"})
    assert "Проверьте номер телефона" in bad_phone.text

    # Пруток 11,7 м — по длине подходит только длинномер; 18 км укладываются в его 30 включённых: 18 500 ₽
    async with SessionLocal() as s:
        long_truck = await s.scalar(select(DeliveryVehicle.id).where(DeliveryVehicle.name == "Длинномер до 25 т"))
    r = await shop.post(
        "/cart/checkout/",
        data={
            "phone": "8 916 123-45-67",
            "name": "Иван",
            "delivery": "delivery",
            "address": "Подольск, ул. Мира, 5",
            "distance_km": "18",
            "vehicle_id": long_truck,
        },
    )
    assert r.status_code == 200 and "Заказ №" in r.text and "1\u00a0676,03" in r.text  # товары: 506,03 + 1170
    async with SessionLocal() as s:
        lead = await s.scalar(select(Lead).order_by(Lead.id.desc()).limit(1))
    assert lead.phone == "+79161234567" and lead.product_name == "Корзина: 2 поз."
    assert lead.calc["kind"] == "cart" and len(lead.calc["items"]) == 2 and lead.calc["goods_kop"] == 167603
    assert lead.calc["total_kop"] == 167603 + 1850000  # товары + доставка
    assert "Подольск" in lead.comment
    # Корзина очищена, и счётчик в шапке страницы «Заказ принят» уже пустой
    assert re.search(r"data-cart-count\s+hidden", r.text)
    assert "В корзине пока ничего нет" in (await shop.get("/cart/")).text


async def test_product_page_has_add_to_cart_button(client):
    """002:FR-001: на карточке есть «В корзину»."""
    html = (await client.get(REBAR)).text
    assert 'formaction="/cart/add/"' in html and 'name="product_id"' in html


async def test_admin_shows_cart_order_items():
    """002:FR-018: позиции заказа в админке, данные покупателя — текстом."""
    from app.admin.leads import _lead_calc_html

    html = str(
        _lead_calc_html(
            {
                "kind": "cart",
                "total_kop": 167603,
                "delivery": "delivery",
                "address": "Подольск, <ул. Мира>",
                "items": [
                    {"name": "Арматура 12 мм А500С", "url": REBAR, "pieces": 1, "meters": "11.7", "total_kop": 50603}
                ],
            }
        )
    )
    assert "Арматура 12 мм А500С" in html and "Итого: 1 676,03" in html
    assert "&lt;ул. Мира&gt;" in html  # адрес от покупателя экранируется
