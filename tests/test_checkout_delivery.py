"""Подзадачи 6–9 на странице корзины: машина и километры, покупатель и оплата, снимок в заявке, подсказка.

Поля формы оформления (POST /cart/checkout/):
- distance_km — расстояние до объекта, км (вводит покупатель; на этапе 2 посчитает карта);
- vehicle_id — выбранная машина;
- buyer_type — person | company; для company — company_name и inn;
- payment — cash (наличными или картой при получении) | invoice (по счёту, только для организаций и ИП).
Пересчёт без JavaScript: GET /cart/?distance_km=18 — те же карточки машин, уже с ценами.

Груз в тестах — арматура 12 мм А500С (пруток 11,7 м, 0,888 кг/м):
- один пруток целиком: 10,39 кг, 11,7 м — по длине подходит только длинномер;
- 10 отрезков по 2 м: 20,78 кг, 2 м — подходит любая машина.
"""

import re

import httpx
import pytest_asyncio
from sqlalchemy import delete, select

from app.catalog.models import Category, Price, Product, Unit
from app.core.db import SessionLocal
from app.core.templating import format_rub
from app.delivery.models import DeliveryVehicle
from app.leads.models import Lead
from app.main import app as fastapi_app

PHONE = "+7 916 123-45-67"
ADDRESS = "Подольск, ул. Мира, 5"

SMALL, TRUCK, CRANE, LONG = "Грузовик до 1,2 т", "Грузовик до 5 т", "Манипулятор до 10 т", "Длинномер до 25 т"


@pytest_asyncio.fixture
async def shop():
    """Отдельный покупатель со своей корзиной."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fastapi_app), base_url="http://testserver") as c:
        yield c


async def rebar_id() -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(Product.id).where(Product.path.like("armatura/%12-mm-a500s")))


async def vehicle_id(name: str) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(DeliveryVehicle.id).where(DeliveryVehicle.name == name))


async def add_whole_bar(shop) -> None:
    await shop.post("/cart/add/", data={"product_id": await rebar_id(), "unit": "m", "qty": "11,7"})


async def add_short_pieces(shop) -> None:
    data = {"product_id": await rebar_id(), "unit": "m", "cut": "1", "cut_len": "2", "cut_count": "10"}
    await shop.post("/cart/add/", data=data)


def order(**extra) -> dict:
    """Заказ с доставкой длинномером на 18 км — частный покупатель, оплата при получении."""
    return {"phone": PHONE, "name": "Иван", "delivery": "delivery", "address": ADDRESS, **extra}


async def last_lead() -> Lead:
    async with SessionLocal() as s:
        return await s.scalar(select(Lead).order_by(Lead.id.desc()).limit(1))


def radio(html: str, vid: int) -> str:
    match = re.search(rf'<input[^>]*name="vehicle_id"[^>]*value="{vid}"[^>]*>', html)
    assert match, f"нет карточки машины {vid}"
    return match.group(0)


# ---------- Подзадача 6: машины на странице корзины ----------


async def test_cart_shows_vehicles_with_prices_for_distance(shop):
    await add_short_pieces(shop)
    html = (await shop.get("/cart/", params={"distance_km": "18"})).text
    for name in (SMALL, TRUCK, CRANE, LONG):
        assert name in html
        assert "disabled" not in radio(html, await vehicle_id(name))  # 2 м и 21 кг — подходит любая
    assert format_rub(354_000) in html  # грузовик до 1,2 т: 1 850 + 13 × 130
    assert format_rub(360_000) in html  # грузовик до 5 т: 2 400 + 8 × 150
    assert 'name="distance_km"' in html and 'value="18"' in html


async def test_unsuitable_vehicles_are_disabled_with_reason(shop):
    await add_whole_bar(shop)
    html = (await shop.get("/cart/", params={"distance_km": "18"})).text
    assert "disabled" in radio(html, await vehicle_id(SMALL))
    assert "disabled" in radio(html, await vehicle_id(TRUCK))
    assert "disabled" not in radio(html, await vehicle_id(LONG))
    assert "Не влезет" in html  # пруток 11,7 м длиннее кузова


async def test_without_distance_vehicles_have_no_price_yet(shop):
    await add_short_pieces(shop)
    html = (await shop.get("/cart/")).text
    assert LONG in html and "Укажите расстояние" in html
    assert format_rub(1_850_000) not in html


async def test_beyond_max_distance_price_is_up_to_manager(shop):
    await add_short_pieces(shop)
    html = (await shop.get("/cart/", params={"distance_km": "250"})).text
    assert "Дальше 200 км стоимость доставки уточнит менеджер" in html


async def test_tariffs_link_on_cart_page(shop):
    await add_short_pieces(shop)
    assert 'href="/delivery/"' in (await shop.get("/cart/")).text


async def test_checkout_requires_distance_and_vehicle(shop):
    await add_whole_bar(shop)
    long_id = await vehicle_id(LONG)

    r = await shop.post("/cart/checkout/", data=order(vehicle_id=long_id))
    assert r.status_code == 422 and "Укажите расстояние до объекта" in r.text

    r = await shop.post("/cart/checkout/", data=order(vehicle_id=long_id, distance_km="далеко"))
    assert r.status_code == 422 and "Расстояние: введите число" in r.text

    r = await shop.post("/cart/checkout/", data=order(distance_km="18"))
    assert r.status_code == 422 and "Выберите машину" in r.text

    r = await shop.post("/cart/checkout/", data=order(distance_km="18", vehicle_id="999999"))
    assert r.status_code == 422 and "Выберите машину" in r.text

    r = await shop.post("/cart/checkout/", data=order(distance_km="18", vehicle_id=await vehicle_id(SMALL)))
    assert r.status_code == 422 and "не подходит" in r.text  # пруток 11,7 м в кузов 3 м не влезет


async def test_checkout_with_delivery_adds_delivery_to_total(shop):
    await add_whole_bar(shop)
    r = await shop.post("/cart/checkout/", data=order(distance_km="18", vehicle_id=await vehicle_id(LONG)))
    assert r.status_code == 200 and "Заказ №" in r.text
    assert LONG in r.text
    assert format_rub(1_850_000) in r.text  # доставка
    assert format_rub(50_603 + 1_850_000) in r.text  # итого: товары + доставка


async def test_pickup_needs_no_distance_or_vehicle(shop):
    await add_whole_bar(shop)
    r = await shop.post("/cart/checkout/", data={"phone": PHONE, "delivery": "pickup"})
    assert r.status_code == 200
    lead = await last_lead()
    assert lead.calc["delivery_kop"] == 0 and "vehicle" not in lead.calc


async def test_too_heavy_for_any_vehicle_is_accepted_for_manager(shop):
    # 40 000 м арматуры ≈ 35,5 т — больше любой машины: заказ принимаем, рейсы посчитает менеджер
    await shop.post("/cart/add/", data={"product_id": await rebar_id(), "unit": "m", "qty": "40000"})
    html = (await shop.get("/cart/", params={"distance_km": "18"})).text
    assert "Ни одна машина не увезёт заказ за один рейс" in html
    r = await shop.post("/cart/checkout/", data=order(distance_km="18"))
    assert r.status_code == 200
    lead = await last_lead()
    assert lead.calc["vehicle"] is None and lead.calc["delivery_kop"] is None


@pytest_asyncio.fixture
async def unknown_weight_item():
    """Штучный товар без веса и длины — машину подтвердит менеджер."""
    async with SessionLocal() as s:
        category = await s.scalar(select(Category).where(Category.path == "armatura"))
        product = Product(
            category_id=category.id, slug="test-khomut", path="armatura/test-khomut", name="Хомут тестовый",
            base_unit=Unit.PIECE, prices=[Price(unit=Unit.PIECE, amount_kop=5000)],
        )  # fmt: skip
        s.add(product)
        await s.commit()
        yield product.id
        await s.execute(delete(Product).where(Product.id == product.id))
        await s.commit()


async def test_unknown_weight_shows_every_vehicle_for_manager(shop, unknown_weight_item):
    await shop.post("/cart/add/", data={"product_id": unknown_weight_item, "unit": "pcs", "qty": "3"})
    html = (await shop.get("/cart/", params={"distance_km": "18"})).text
    assert "Машину подтвердит менеджер" in html
    for name in (SMALL, TRUCK, CRANE, LONG):
        assert "disabled" not in radio(html, await vehicle_id(name))


# ---------- Подзадача 7: тип покупателя и способ оплаты ----------


async def test_cart_has_buyer_and_payment_fields(shop):
    await add_short_pieces(shop)
    html = (await shop.get("/cart/")).text
    for value in ("person", "company"):
        assert re.search(rf'name="buyer_type"[^>]*value="{value}"', html)
    for value in ("cash", "invoice"):
        assert re.search(rf'name="payment"[^>]*value="{value}"', html)
    assert 'name="company_name"' in html and 'name="inn"' in html


async def test_company_requires_name_and_valid_inn(shop):
    await add_short_pieces(shop)
    base = order(distance_km="18", vehicle_id=await vehicle_id(TRUCK), buyer_type="company", payment="invoice")

    r = await shop.post("/cart/checkout/", data={**base, "inn": "7707083893"})
    assert r.status_code == 422 and "Укажите название организации" in r.text

    r = await shop.post("/cart/checkout/", data={**base, "company_name": "ООО «Ромашка»", "inn": "7707083894"})
    assert r.status_code == 422 and "Проверьте ИНН" in r.text


async def test_invoice_is_only_for_companies(shop):
    await add_short_pieces(shop)
    data = order(distance_km="18", vehicle_id=await vehicle_id(TRUCK), buyer_type="person", payment="invoice")
    r = await shop.post("/cart/checkout/", data=data)
    assert r.status_code == 422 and "Оплата по счёту — для организаций и ИП" in r.text


async def test_form_keeps_entered_values_after_error(shop):
    await add_short_pieces(shop)
    data = order(distance_km="18", buyer_type="company", company_name="ООО «Ромашка»", inn="7707083893")
    r = await shop.post("/cart/checkout/", data=data)  # машина не выбрана
    assert r.status_code == 422
    assert 'value="ООО «Ромашка»"' in r.text and 'value="7707083893"' in r.text and 'value="18"' in r.text


# ---------- Подзадача 8: снимок доставки, покупателя и оплаты в заявке ----------


async def test_lead_keeps_delivery_buyer_and_payment_snapshot(shop):
    await add_short_pieces(shop)
    truck = await vehicle_id(TRUCK)
    data = order(
        distance_km="18",
        vehicle_id=truck,
        buyer_type="company",
        company_name="ООО «Ромашка»",
        inn="7707 0838 93",  # пробелы при вводе — не ошибка
        payment="invoice",
    )
    r = await shop.post("/cart/checkout/", data=data)
    assert r.status_code == 200, r.text[-800:]
    calc = (await last_lead()).calc
    assert calc["vehicle"] == {"id": truck, "name": TRUCK, "distance_km": "18", "price_kop": 360_000}
    assert calc["buyer"] == {"type": "company", "company_name": "ООО «Ромашка»", "inn": "7707083893"}
    assert calc["payment"] == "invoice"
    goods = sum(item["total_kop"] for item in calc["items"])
    assert (calc["goods_kop"], calc["delivery_kop"], calc["total_kop"]) == (goods, 360_000, goods + 360_000)


async def test_person_paying_cash_is_default(shop):
    await add_short_pieces(shop)
    r = await shop.post("/cart/checkout/", data=order(distance_km="18", vehicle_id=await vehicle_id(TRUCK)))
    assert r.status_code == 200
    calc = (await last_lead()).calc
    assert calc["buyer"] == {"type": "person"} and calc["payment"] == "cash"


async def test_lead_price_unknown_beyond_max_distance(shop):
    await add_short_pieces(shop)
    r = await shop.post("/cart/checkout/", data=order(distance_km="250", vehicle_id=await vehicle_id(TRUCK)))
    assert r.status_code == 200
    calc = (await last_lead()).calc
    assert calc["vehicle"]["price_kop"] is None and calc["delivery_kop"] is None
    assert calc["total_kop"] == calc["goods_kop"]  # доставку посчитает менеджер
    assert "уточнит менеджер" in r.text


async def test_lead_snapshot_does_not_change_with_tariff(shop):
    await add_short_pieces(shop)
    truck = await vehicle_id(TRUCK)
    await shop.post("/cart/checkout/", data=order(distance_km="18", vehicle_id=truck))
    lead_id = (await last_lead()).id
    async with SessionLocal() as s:
        vehicle = await s.get(DeliveryVehicle, truck)
        vehicle.base_price_kop = 999_900
        await s.commit()
        try:
            lead = await s.get(Lead, lead_id)
            assert lead.calc["vehicle"]["price_kop"] == 360_000
        finally:
            vehicle.base_price_kop = 240_000
            await s.commit()


def test_admin_shows_delivery_buyer_and_payment():
    from app.admin.leads import _lead_calc_html

    html = str(
        _lead_calc_html(
            {
                "kind": "cart",
                "items": [
                    {"name": "Арматура 12 мм А500С", "url": "/catalog/x/", "meters": "23.4", "total_kop": 101205}
                ],
                "delivery": "delivery",
                "address": ADDRESS,
                "vehicle": {"id": 2, "name": TRUCK, "distance_km": "18", "price_kop": 360_000},
                "buyer": {"type": "company", "company_name": "ООО <Ромашка>", "inn": "7707083893"},
                "payment": "invoice",
                "goods_kop": 101_205,
                "delivery_kop": 360_000,
                "total_kop": 461_205,
            }
        )
    )
    assert TRUCK in html and "18 км" in html and format_rub(360_000) in html
    assert "ООО &lt;Ромашка&gt;" in html and "ИНН 7707083893" in html  # данные покупателя экранируются
    assert "По счёту" in html
    assert f"Итого: {format_rub(461_205)}" in html


def test_admin_shows_delivery_price_unknown():
    from app.admin.leads import _lead_calc_html

    html = str(
        _lead_calc_html(
            {
                "kind": "cart",
                "items": [],
                "delivery": "delivery",
                "address": ADDRESS,
                "vehicle": {"id": 2, "name": TRUCK, "distance_km": "250", "price_kop": None},
                "buyer": {"type": "person"},
                "payment": "cash",
                "goods_kop": 0,
                "delivery_kop": None,
                "total_kop": 0,
            }
        )
    )
    assert "уточнить" in html.lower() or "уточнит" in html.lower()


# ---------- Карта склада в блоке доставки (до ключа API — виджет без ключа) ----------


async def test_cart_shows_warehouse_map_and_route_link(shop):
    from markupsafe import escape

    from app.core.maps import yandex_map

    await add_short_pieces(shop)
    html = (await shop.get("/cart/")).text
    view = yandex_map()
    assert f'src="{escape(view.widget_src)}"' in html  # тот же виджет, что на «Контактах»
    map_block = html.split('class="delivery-map', 1)[1].split("</div>", 1)[0]
    assert "<iframe" in map_block and 'loading="lazy"' in map_block
    assert f'href="{escape(view.route_url or view.open_url)}"' in html  # маршрут от склада — посмотреть км
