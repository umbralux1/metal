"""Формула цены доставки: базовая цена за первые км, дальше — за каждый начатый километр. Без базы."""

from decimal import Decimal

import pytest

from app.core.config import settings
from app.delivery.pricing import DistanceError, Tariff, delivery_price_kop

MAX_KM = 200

# Тарифы начальных машин (app/delivery/seed.py), в копейках
SMALL = Tariff(base_price_kop=185_000, included_km=5, price_per_km_kop=13_000)  # грузовик до 1,2 т
TRUCK = Tariff(base_price_kop=240_000, included_km=10, price_per_km_kop=15_000)  # грузовик до 5 т
LONG = Tariff(base_price_kop=1_850_000, included_km=30, price_per_km_kop=18_000)  # длинномер


@pytest.mark.parametrize(
    ("tariff", "km", "price_kop"),
    [
        (SMALL, 3, 185_000),  # меньше включённых — только базовая
        (SMALL, 5, 185_000),  # ровно включённые — без доплаты
        (TRUCK, 18, 360_000),  # 2 400 + (18 − 10) × 150 = 3 600 ₽
        (LONG, 41, 2_048_000),  # 18 500 + 11 × 180 = 20 480 ₽ — как у конкурента
        (TRUCK, 0, 240_000),  # 0 км — всё равно базовая: подача машины
    ],
    ids=["below-included", "exactly-included", "truck-18km", "long-41km", "zero-km"],
)
def test_price(tariff, km, price_kop):
    assert delivery_price_kop(tariff, km, MAX_KM) == price_kop


@pytest.mark.parametrize(
    ("km", "price_kop"),
    [
        (Decimal("10.3"), 255_000),  # начатый 11-й км — доплата за целый
        (Decimal("10.0"), 240_000),
        (Decimal("17.01"), 360_000),  # 7,01 км сверх → 8 км
        (Decimal("9.99"), 240_000),
    ],
)
def test_partial_km_rounds_up(km, price_kop):
    assert delivery_price_kop(TRUCK, km, MAX_KM) == price_kop


def test_zero_price_per_km_is_fixed_price():
    fixed = Tariff(base_price_kop=300_000, included_km=0, price_per_km_kop=0)
    assert delivery_price_kop(fixed, 150, MAX_KM) == 300_000


def test_price_never_decreases_with_distance():
    prices = [delivery_price_kop(TRUCK, Decimal(km) / 10, MAX_KM) for km in range(0, MAX_KM * 10 + 1)]
    assert prices == sorted(prices)


def test_max_distance_is_allowed():
    assert delivery_price_kop(TRUCK, MAX_KM, MAX_KM) == 240_000 + (MAX_KM - 10) * 15_000


@pytest.mark.parametrize("km", [Decimal("200.1"), 201, 4100])
def test_beyond_max_distance_needs_manager(km):
    with pytest.raises(DistanceError, match="уточнит менеджер"):
        delivery_price_kop(TRUCK, km, MAX_KM)


@pytest.mark.parametrize("km", [-1, Decimal("-0.1")])
def test_negative_distance_is_rejected(km):
    with pytest.raises(DistanceError, match="не может быть отрицательным"):
        delivery_price_kop(TRUCK, km, MAX_KM)


def test_tariff_is_immutable():
    with pytest.raises(AttributeError):
        TRUCK.base_price_kop = 0  # type: ignore[misc]


def test_max_distance_setting_defaults_to_200():
    """Предел — настройка DELIVERY_MAX_KM: дальше цену не считаем, уточняет менеджер."""
    assert settings.delivery_max_km == 200
