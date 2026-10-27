"""Корзина и оформление заказа (specs/002-cart-checkout): доработки и требования, у которых не было тестов."""

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, update

from app.cart.store import COOKIE
from app.catalog.models import Category, Price, Product, Unit
from app.core.db import SessionLocal
from app.leads.models import Lead
from app.leads.phone import normalize_phone
from app.main import app as fastapi_app

FETCH = {"X-Requested-With": "fetch"}


@pytest_asyncio.fixture
async def shop():
    """Отдельный покупатель со своей корзиной."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fastapi_app), base_url="http://testserver") as c:
        yield c


async def pid(path: str = "armatura/12-mm/12-mm-a500s") -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(Product.id).where(Product.path == path))


async def lead_count() -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(Lead))


@pytest_asyncio.fixture
async def own_product():
    """Свой товар по 50 ₽ за штуку: тест меняет ему цену и снимает с продажи, не трогая общий каталог."""
    async with SessionLocal() as s:
        category = await s.scalar(select(Category).where(Category.path == "armatura"))
        product = Product(
            category_id=category.id, slug="test-own", path="armatura/test-own", name="Свой товар",
            base_unit=Unit.PIECE, prices=[Price(unit=Unit.PIECE, amount_kop=5000)],
        )  # fmt: skip
        s.add(product)
        await s.commit()
        yield product
        await s.execute(delete(Product).where(Product.id == product.id))
        await s.commit()


# ---------- Доработки ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("495 123-45-67", "+74951234567"),
        ("(812) 123-45-67", "+78121234567"),
        ("916 123-45-67", "+79161234567"),
        ("+7 495 123-45-67", "+74951234567"),
        ("12345", None),
    ],
)
def test_phone_without_country_code_is_russian(raw, expected):
    """002:FR-011: любые 10 цифр без кода страны — российский номер +7, мобильный или городской."""
    assert normalize_phone(raw) == expected


async def test_checkout_accepts_city_phone_without_code(shop):
    """002:FR-011: заказ с городским номером без кода «495 123-45-67» принимается."""
    await shop.post("/cart/add/", data={"product_id": await pid(), "unit": "m", "qty": "11,7"})
    r = await shop.post("/cart/checkout/", data={"phone": "495 123-45-67", "delivery": "pickup"})
    assert r.status_code == 200 and "Заказ №" in r.text


async def test_order_done_page_shows_quantities(shop):
    """002:FR-016: на странице «Заказ принят» у позиций количество — штуки, метры, резка — и сумма."""
    rebar = await pid()
    await shop.post("/cart/add/", data={"product_id": rebar, "unit": "m", "qty": "11,7"})
    cut = {"product_id": rebar, "unit": "m", "cut": "1", "cut_len": "3,9", "cut_count": "10"}
    await shop.post("/cart/add/", data=cut)
    r = await shop.post("/cart/checkout/", data={"phone": "+7 916 123-45-67", "delivery": "pickup"})
    items = r.text.split('class="order-items"')[1].split("</ul>")[0]
    assert "1 шт." in items and "11,7 м" in items
    assert "резка 10 × 3,9 м" in items


# ---------- Требования без тестов (охранные: поведение уже есть) ----------


async def test_retired_product_is_not_added(shop, own_product):
    """002:FR-004: снятый с продажи товар в корзину не кладётся, покупатель видит ошибку."""
    async with SessionLocal() as s:
        await s.execute(update(Product).where(Product.id == own_product.id).values(is_active=False))
        await s.commit()
    r = await shop.post("/cart/add/", data={"product_id": own_product.id, "unit": "pcs", "qty": "1"}, headers=FETCH)
    assert r.status_code == 422 and "Товар не найден" in r.json()["error"]


async def test_cart_shows_current_price(shop, own_product):
    """002:FR-005: цена изменилась после добавления — корзина показывает новую."""
    await shop.post("/cart/add/", data={"product_id": own_product.id, "unit": "pcs", "qty": "2"})
    assert "100 ₽" in (await shop.get("/cart/")).text  # 2 × 50 ₽
    async with SessionLocal() as s:
        await s.execute(update(Price).where(Price.product_id == own_product.id).values(amount_kop=7000))
        await s.commit()
    assert "140 ₽" in (await shop.get("/cart/")).text  # 2 × 70 ₽


async def test_thirty_first_line_is_rejected(shop):
    """002:FR-008: в корзине не больше 30 позиций — дальше «оформите заказ или позвоните нам»."""
    rebar = await pid()
    for i in range(30):
        cut = {"product_id": rebar, "unit": "m", "cut": "1", "cut_len": f"1,{i:02d}", "cut_count": "1"}
        assert (await shop.post("/cart/add/", data=cut, headers=FETCH)).json()["ok"]
    extra = {"product_id": rebar, "unit": "m", "cut": "1", "cut_len": "5,55", "cut_count": "1"}
    r = await shop.post("/cart/add/", data=extra, headers=FETCH)
    assert r.status_code == 422 and "30 позиций" in r.json()["error"]


async def test_cart_cookie_lives_30_days_and_is_hidden_from_scripts(shop):
    """002:FR-009: корзина хранится 30 дней с последнего изменения; скрипты страницы её не читают."""
    r = await shop.post("/cart/add/", data={"product_id": await pid(), "unit": "m", "qty": "11,7"})
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=") and "Max-Age=2592000" in cookie
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie


async def test_empty_cart_and_honeypot_create_no_order(shop):
    """002:FR-017: пустая корзина и ловушка для ботов — возврат в корзину без заказа."""
    before = await lead_count()
    empty = await shop.post("/cart/checkout/", data={"phone": "+7 916 123-45-67", "delivery": "pickup"})
    assert empty.status_code == 303 and empty.headers["location"] == "/cart/"
    await shop.post("/cart/add/", data={"product_id": await pid(), "unit": "m", "qty": "11,7"})
    bot = await shop.post(
        "/cart/checkout/", data={"phone": "+7 916 123-45-67", "delivery": "pickup", "website": "spam.example"}
    )
    assert bot.status_code == 303 and bot.headers["location"] == "/cart/"
    assert await lead_count() == before
