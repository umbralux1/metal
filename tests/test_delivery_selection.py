"""Подзадачи 5 и 9: подбор машин под груз и подсказка «дешевле с резкой».

app.delivery.selection — чистые функции, без базы:
- Vehicle — машина для подбора: грузоподъёмность, длина кузова, тариф;
- quote_vehicles(vehicles, cargo, distance_km, max_km) -> list[VehicleQuote] — каждая машина: влезает ли
  по весу и длине и цена доставки. Порядок — как пришли (из базы — по полю «Порядок»);
- cut_hint(quotes, min_length_m) -> CutHint | None — машина дешевле, которая не берёт заказ только из-за длины,
  а порезать заказ можно до её кузова.
app.delivery.service.list_active_vehicles(session) — активные машины из базы в порядке «Порядок».
"""

from decimal import Decimal as D

import pytest
from sqlalchemy import select, update

from app.core.db import SessionLocal
from app.delivery.cargo import CargoSpec
from app.delivery.models import DeliveryVehicle
from app.delivery.pricing import DistanceError, Tariff
from app.delivery.selection import CutHint, Vehicle, cheapest_fit, cut_hint, quote_vehicles
from app.delivery.service import list_active_vehicles

MAX_KM = 200

# Начальные машины (app/delivery/seed.py)
SMALL = Vehicle(1, "Грузовик до 1,2 т", 1200, D(3), True, Tariff(185_000, 5, 13_000))
TRUCK = Vehicle(2, "Грузовик до 5 т", 5000, D(6), True, Tariff(240_000, 10, 15_000))
CRANE = Vehicle(3, "Манипулятор до 10 т", 10000, D(8), False, Tariff(1_500_000, 25, 19_000))
LONG = Vehicle(4, "Длинномер до 25 т", 25000, D("13.5"), True, Tariff(1_850_000, 30, 18_000))
FLEET = [SMALL, TRUCK, CRANE, LONG]


def by_name(quotes):
    return {q.vehicle.name: q for q in quotes}


# ---------- Подзадача 5: подбор ----------


def test_light_short_cargo_fits_every_vehicle():
    quotes = quote_vehicles(FLEET, CargoSpec(D(500), D("2.5"), True), D(18), MAX_KM)
    assert [q.vehicle.name for q in quotes] == [v.name for v in FLEET]  # порядок сохраняется
    assert all(q.fits for q in quotes)
    assert by_name(quotes)["Грузовик до 5 т"].price_kop == 360_000  # 2 400 + 8 × 150


def test_heavy_cargo_does_not_fit_small_trucks():
    quotes = by_name(quote_vehicles(FLEET, CargoSpec(D(6000), D(6), True), D(18), MAX_KM))
    assert not quotes["Грузовик до 1,2 т"].fits_weight
    assert not quotes["Грузовик до 5 т"].fits_weight and quotes["Грузовик до 5 т"].fits_length
    assert quotes["Манипулятор до 10 т"].fits and quotes["Длинномер до 25 т"].fits


def test_long_bars_fit_only_long_truck():
    # Прутки 11,7 м: по весу 93 кг влезут куда угодно, по длине — только длинномер
    quotes = by_name(quote_vehicles(FLEET, CargoSpec(D("93.51"), D("11.7"), True), D(18), MAX_KM))
    assert [name for name, q in quotes.items() if q.fits] == ["Длинномер до 25 т"]
    assert quotes["Грузовик до 5 т"].fits_weight and not quotes["Грузовик до 5 т"].fits_length


def test_exact_limits_fit():
    quotes = by_name(quote_vehicles(FLEET, CargoSpec(D(1200), D(3), True), D(5), MAX_KM))
    assert quotes["Грузовик до 1,2 т"].fits


def test_too_heavy_for_every_vehicle():
    quotes = quote_vehicles(FLEET, CargoSpec(D(30_000), D(6), True), D(18), MAX_KM)
    assert not any(q.fits for q in quotes)
    assert cheapest_fit(quotes) is None


def test_incomplete_cargo_shows_every_vehicle():
    """Вес или длина неизвестны — показываем все машины, выбор подтвердит менеджер."""
    quotes = quote_vehicles(FLEET, CargoSpec(D(0), D(0), False), D(18), MAX_KM)
    assert all(q.fits for q in quotes)


def test_no_distance_yet_means_no_price():
    quotes = quote_vehicles(FLEET, CargoSpec(D(100), D(2), True), None, MAX_KM)
    assert all(q.price_kop is None for q in quotes) and all(q.fits for q in quotes)


def test_beyond_max_distance_means_no_price_not_error():
    quotes = quote_vehicles(FLEET, CargoSpec(D(100), D(2), True), D(250), MAX_KM)
    assert all(q.price_kop is None for q in quotes)


def test_negative_distance_is_an_error():
    with pytest.raises(DistanceError):
        quote_vehicles(FLEET, CargoSpec(D(100), D(2), True), D(-1), MAX_KM)


def test_cheapest_fit_takes_lowest_price_among_fitting():
    quotes = quote_vehicles(FLEET, CargoSpec(D(6000), D(6), True), D(18), MAX_KM)
    assert cheapest_fit(quotes).vehicle.name == "Манипулятор до 10 т"  # 15 000 < 18 500


def test_cheapest_fit_ignores_unpriced():
    assert cheapest_fit(quote_vehicles(FLEET, CargoSpec(D(1), D(1), True), None, MAX_KM)) is None


# ---------- Подзадача 9: «дешевле с резкой» ----------


def test_cut_hint_for_long_bars():
    # Один пруток 11,7 м на 18 км: длинномер — 18 500 ₽. Порезать до 3 м — повезёт грузовик до 1,2 т за 3 540 ₽
    quotes = quote_vehicles(FLEET, CargoSpec(D("10.39"), D("11.7"), True), D(18), MAX_KM)
    hint = cut_hint(quotes, min_length_m=D(0))
    assert hint == CutHint(vehicle=SMALL, cut_to_m=D(3), price_kop=354_000, instead_kop=1_850_000)


def test_cut_hint_respects_what_cannot_be_cut():
    # В заказе ещё листы 2,5 м — резать их не будем: самый короткий возможный груз 2,5 м, грузовику до 1,2 т (3 м)
    # подходит; а сваи 4 м — уже нет, остаётся грузовик до 5 т
    quotes = quote_vehicles(FLEET, CargoSpec(D(500), D("11.7"), True), D(18), MAX_KM)
    assert cut_hint(quotes, min_length_m=D("2.5")).vehicle == SMALL
    assert cut_hint(quotes, min_length_m=D(4)).vehicle == TRUCK


def test_cut_hint_skips_vehicles_too_weak_for_the_weight():
    # 6 т прутков 11,7 м: грузовики до 1,2 и 5 т не возьмут по весу — резка им не поможет.
    # Манипулятор (10 т, кузов 8 м) по весу проходит, мешает длина: 15 000 вместо 18 500
    quotes = quote_vehicles(FLEET, CargoSpec(D(6000), D("11.7"), True), D(18), MAX_KM)
    assert cut_hint(quotes, min_length_m=D(0)).vehicle == CRANE


def test_no_cut_hint_when_already_cheapest():
    quotes = quote_vehicles(FLEET, CargoSpec(D(100), D(2), True), D(18), MAX_KM)
    assert cut_hint(quotes, min_length_m=D(0)) is None


def test_no_cut_hint_without_prices_or_for_incomplete_cargo():
    long_bars = CargoSpec(D(100), D("11.7"), True)
    assert cut_hint(quote_vehicles(FLEET, long_bars, None, MAX_KM), min_length_m=D(0)) is None
    unknown = CargoSpec(D(0), D(0), False)
    assert cut_hint(quote_vehicles(FLEET, unknown, D(18), MAX_KM), min_length_m=D(0)) is None


# ---------- Машины из базы ----------


async def test_list_active_vehicles_in_sort_order():
    async with SessionLocal() as session:
        vehicles = await list_active_vehicles(session)
    assert [v.name for v in vehicles] == [v.name for v in FLEET]
    truck = vehicles[1]
    assert (truck.max_weight_kg, truck.max_length_m, truck.tariff) == (5000, D(6), Tariff(240_000, 10, 15_000))
    assert isinstance(truck, Vehicle)  # модель чтения, не ORM-объект


async def test_inactive_vehicle_is_not_offered():
    async with SessionLocal() as session:
        crane_id = await session.scalar(select(DeliveryVehicle.id).where(DeliveryVehicle.name == CRANE.name))
        await session.execute(update(DeliveryVehicle).where(DeliveryVehicle.id == crane_id).values(is_active=False))
        await session.commit()
        try:
            names = [v.name for v in await list_active_vehicles(session)]
            assert CRANE.name not in names and len(names) == 3
        finally:
            await session.execute(update(DeliveryVehicle).where(DeliveryVehicle.id == crane_id).values(is_active=True))
            await session.commit()
