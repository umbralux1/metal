"""Админка, раздел «Доставка → Машины»: список, цены в рублях, проверка значений, без удаления."""

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.core.templating import format_rub
from app.delivery.models import DeliveryVehicle
from app.delivery.seed import DEFAULT_VEHICLES

URL = "/admin/delivery-vehicle"
TEST_NAME = "Тестовая газель"

# Форма новой машины. Цены — в рублях, в базу уходят копейки
FORM = {
    "name": TEST_NAME,
    "max_weight_kg": "1500",
    "max_length_m": "4,2",
    "base_price_rub": "2 000,50",
    "included_km": "7",
    "price_per_km_rub": "140",
    "self_unloading": "y",
    "sort": "15",
    "is_active": "y",
}


async def get_vehicle(name: str) -> DeliveryVehicle | None:
    async with SessionLocal() as session:
        return await session.scalar(select(DeliveryVehicle).where(DeliveryVehicle.name == name))


@pytest_asyncio.fixture
async def cleanup():
    """Удаляет тестовую машину: начальные тарифы проверяет tests/test_delivery_vehicles.py."""
    yield
    async with SessionLocal() as session:
        await session.execute(delete(DeliveryVehicle).where(DeliveryVehicle.name == TEST_NAME))
        await session.commit()


async def test_requires_login(client):
    r = await client.get(f"{URL}/list")
    assert r.status_code in (302, 303)
    assert "/admin/login" in r.headers["location"]


async def test_menu_has_delivery_group(admin):
    html = (await admin.get("/admin/")).text
    assert "Доставка" in html and "Машины" in html


async def test_list_shows_vehicles_in_order_with_rub_prices(admin):
    r = await admin.get(f"{URL}/list")
    assert r.status_code == 200
    names = [v["name"] for v in sorted(DEFAULT_VEHICLES, key=lambda v: v["sort"])]
    positions = [r.text.index(name) for name in names]
    assert positions == sorted(positions), "машины должны идти по sort: от маленькой к большой"
    assert format_rub(185_000) in r.text  # базовая цена грузовика до 1,2 т — в рублях, не 185000
    assert format_rub(13_000) in r.text  # цена за км


async def test_edit_form_shows_rubles(admin):
    vehicle = await get_vehicle("Грузовик до 1,2 т")
    form = (await admin.get(f"{URL}/edit/{vehicle.id}")).text
    assert 'name="base_price_rub"' in form and 'value="1850"' in form
    assert 'name="price_per_km_rub"' in form and 'value="130"' in form
    assert 'name="base_price_kop"' not in form  # копейки в форме не показываем


async def test_create_saves_kopecks(admin, cleanup):
    r = await admin.post(f"{URL}/create", data=FORM)
    assert r.status_code == 302, r.text[:500]
    vehicle = await get_vehicle(TEST_NAME)
    assert vehicle.base_price_kop == 200_050
    assert vehicle.price_per_km_kop == 14_000
    assert (vehicle.max_weight_kg, vehicle.included_km, vehicle.sort) == (1500, 7, 15)
    assert str(vehicle.max_length_m) == "4.20"
    assert vehicle.self_unloading and vehicle.is_active


async def test_edit_changes_price_and_deactivates(admin, cleanup):
    await admin.post(f"{URL}/create", data=FORM)
    vehicle = await get_vehicle(TEST_NAME)
    form = {**FORM, "base_price_rub": "2100", "price_per_km_rub": "0"}
    del form["is_active"]  # снятая галочка не отправляется
    r = await admin.post(f"{URL}/edit/{vehicle.id}", data=form)
    assert r.status_code == 302, r.text[:500]
    vehicle = await get_vehicle(TEST_NAME)
    assert vehicle.base_price_kop == 210_000
    assert vehicle.price_per_km_kop == 0  # фиксированная цена без доплаты за км — допустима
    assert not vehicle.is_active


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("max_weight_kg", "0", "Грузоподъёмность должна быть больше 0"),
        ("max_length_m", "0", "Длина груза должна быть больше 0"),
        ("included_km", "-1", "не может быть отрицательным"),
        ("base_price_rub", "-100", "не может быть отрицательной"),
        ("base_price_rub", "сорок", "введите число"),
        ("base_price_rub", "", "Укажите базовую цену"),
        ("price_per_km_rub", "1,234", "не больше двух знаков"),
    ],
    ids=["weight-0", "length-0", "km-negative", "price-negative", "price-letters", "price-empty", "price-3-decimals"],
)
async def test_invalid_values_are_rejected(admin, cleanup, field, value, error):
    r = await admin.post(f"{URL}/create", data={**FORM, field: value})
    assert r.status_code == 400, f"{field}={value!r}: ожидали ошибку формы, получили {r.status_code}"
    assert error in r.text
    assert await get_vehicle(TEST_NAME) is None


async def test_duplicate_name_is_rejected(admin):
    r = await admin.post(f"{URL}/create", data={**FORM, "name": "Грузовик до 5 т"})
    assert r.status_code == 400
    assert "уже есть" in r.text


async def test_no_delete(admin):
    html = (await admin.get(f"{URL}/list")).text
    assert f"{URL}/delete" not in html
    vehicle = await get_vehicle("Грузовик до 5 т")
    r = await admin.delete(f"{URL}/delete?pks={vehicle.id}")
    assert r.status_code in (403, 404, 405)
    assert await get_vehicle("Грузовик до 5 т") is not None
